"""Diagnostic leases over declared published ports; no management presentation."""
from micros_tooling.storage.packages import require

def stream_operation(management, device, payload):
    """Diagnostic leases/cursors, not MCU requests. Readers share one drain."""
    require(isinstance(payload, dict), 'Invalid stream request')
    action=payload.get('action')
    require(action in ('open','read','close'), 'Unknown stream action')
    hub=management.registry.streams
    with management.registry.changed:
        if action in ('read','close'):
            require(payload.keys() <= {'action','reader','cursor'} and isinstance(payload.get('reader'),str), 'Invalid stream reader')
            if action=='close': return hub.close(device,payload['reader'])
            return hub.read(device,payload['reader'],payload.get('cursor'))
        require(payload.keys() == {'action','base','graph','service','port'}, 'Invalid stream request')
        row=management.registry.db.execute("SELECT boot,status,last_seen,token_hash FROM devices WHERE id=?",(device,)).fetchone()
    import json, time
    require(row and row[1] and row[3] and time.time()-row[2]<30, 'Board offline')
    status=json.loads(row[1])
    require(status.get('platform')=='esp32' and status.get('ipc_stream')==1,
            'Streaming requires an updated ESP32 resident base (IPC stream protocol 1)')
    activation=status.get('activation',{})
    require(not activation.get('pending') and status['identity']['base_sha256']==payload['base']
            and activation.get('good_sha256')==payload['graph'], 'Application changed; refresh the board')
    # Decoration can acquire the flash inventory cache lock; never call it while
    # holding Registry.changed (the cache itself reads registry artifacts).
    decorated=management.decorate(status)
    binding=next((b for b in decorated.get('channel_ports',[]) if b['service']==payload['service'] and b['port']['name']==payload['port']),None)
    require(binding is not None, 'No matching published port')
    require(any(s.get('name')==binding['service'] and s.get('state')=='Running' for s in decorated['services']), 'Service is not running')
    require(binding['instance']<len(status['services']) and status['services'][binding['instance']].get('state')=='Running', 'Bridge is not running')
    with management.registry.changed:
        latest=management.registry.db.execute("SELECT boot,status,token_hash FROM devices WHERE id=?",(device,)).fetchone()
        require(latest and latest[2] and latest[0]==row[0] and json.loads(latest[1]).get('activation')==activation,
                'Application changed while opening capture')
        return hub.open(device,row[0],status,binding)
