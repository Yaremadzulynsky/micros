"""Execute one typed service command and correlate a bounded reply without retrying writes."""
import http.client
import secrets
import time
from google.protobuf.message import DecodeError
from micros_tooling.commands.schema import descriptor, values, MAX_WIRE
from micros_tooling.communication.protobuf import message_class
from micros_tooling.communication.channels import Channels, ChannelMissed
from micros_tooling.storage.packages import require


def operate(management, device, payload, *, clock=time.monotonic, sleep=time.sleep):
    from server.remote import RegistryRemote
    require(isinstance(payload,dict) and payload.keys()=={'base','graph','service','command','args'}
            and all(isinstance(payload[k],str) for k in ('base','graph','service','command')), 'Invalid typed command request')
    management.begin_operation(device)
    request_id=secrets.randbits(64) or 1
    dispatched=False
    def unknown(message):
        management.event(device,'typed-command','unknown',payload['service']+': '+payload['command'])
        return dict(state='unknown',request_id=str(request_id),message=message+' Command was not retried.')
    try:
        remote=RegistryRemote(management.registry,device)
        before=remote.status()
        require(before.get('platform','esp32')=='esp32','Typed remote commands currently require an ESP32 IPC bridge base')
        require(before.get('identity',{}).get('device_id')==device and before['identity']['base_sha256']==payload['base']
                and before['activation']['good_sha256']==payload['graph'] and not before['activation']['pending']
                and not before.get('physical_recovery') and not before.get('deployment_session'), 'Application changed or unavailable; refresh commands')
        binding=next((b for b in management.decorate(before).get('service_commands',[]) if b['service']==payload['service']),None)
        require(binding is not None,'No matching deployed command service')
        contract=binding['contract'];command=payload['command']
        require(command in contract['exposed'],'Command is not exposed on this board')
        require(all(index<len(before['services']) and before['services'][index]['state']=='Running'
                    for index in (binding['instance'],binding['service_index'])),'Service or command bridge is not running')
        require(isinstance(before.get('service_boot'),str) and before['service_boot']
                and all(isinstance(before['services'][i].get('instance'),str) and before['services'][i]['instance']
                        for i in (binding['instance'],binding['service_index'])),
                'Typed commands require a base reporting boot and service instance identities')
        definition=contract['commands'][command]
        arguments=values(definition['args'],payload['args'])
        request_type=message_class(descriptor(contract['api'],contract['commands']))
        response_type=message_class(descriptor(contract['api'],contract['commands'],True))
        message=request_type(request_id=request_id,contract_id=contract['contract_id'])
        nested=getattr(message,command);nested.SetInParent()  # Preserve zero-argument commands in the oneof.
        for key,value in arguments.items():setattr(nested,key,value)
        wire=message.SerializeToString()
        require(len(wire)<=MAX_WIRE,'Command request exceeds the transport bound')
        client=object.__new__(Channels);client.remote=remote;client.instance=binding['instance']
        client.ports={direction:dict(key=contract[direction+'_key'],max_payload=MAX_WIRE,access=access)
                      for direction,access in [('request','publish'),('response','subscribe')]}
        with remote.deployment_session(before):
            # Last replies may be retained. Correlation discards them; never drain other service ports.
            dispatched=True
            client.write('request',wire)
            deadline=clock()+8
            for _ in range(32):
                if clock()>=deadline:break
                try:raw=client.read('response')
                except ChannelMissed:continue
                if raw is None:
                    sleep(.1);continue
                response=response_type.FromString(raw)
                if response.request_id!=request_id:continue
                require(response.contract_id==contract['contract_id'],'Reply command contract differs from the deployed declaration')
                require(response.result<=0,'Invalid handler result code')
                current=remote.status()
                require(current['identity']==before['identity'] and current['activation']==before['activation']
                        and current.get('service_boot')==before.get('service_boot')
                        and len(current['services'])==len(before['services'])
                        and all(current['services'][i].get('instance')==before['services'][i].get('instance')
                                for i in (binding['instance'],binding['service_index'])),
                        'Device or service instance changed while executing the command')
                if response.result:
                    management.event(device,'typed-command','failed',payload['service']+': '+command)
                    return dict(state='failed',request_id=str(request_id),result=response.result,message='Service handler returned an error')
                require(response.WhichOneof('command')==command,'Reply belongs to a different command')
                output=getattr(response,command)
                result={field:getattr(output,field) for field in definition['returns']}
                result=values(definition['returns'],result,decode=True)
                management.event(device,'typed-command','completed',payload['service']+': '+command)
                return dict(state='completed',request_id=str(request_id),result=0,values=result)
            return unknown('No matching handler reply arrived before the response limit.')
    except (ValueError, RuntimeError, DecodeError, OSError, http.client.HTTPException) as error:
        if dispatched:return unknown(str(error))
        raise
    finally:
        management.end_operation(device)
