"""Expand explicit command exposure into ordinary SDK channel and bridge declarations."""
from pathlib import Path
from .schema import normalize, identity, proto, descriptor, MAX_WIRE
from micros_tooling.storage.packages import require, MAX_HANDLES


def prepare(service, selection, contract, channel_definitions, generated_directory):
    exposed=selection.get('expose_commands',[])
    if not contract.get('commands'):
        require(not exposed, 'expose_commands requires commands in the service contract')
        return None
    commands=normalize(contract['commands'],contract.get('types'))
    require(isinstance(exposed,list) and all(isinstance(c,str) and c in commands for c in exposed)
            and len(set(exposed))==len(exposed), 'expose_commands must list declared command names once')
    api=service['_interface']['name']
    spec=dict(api=api,commands=commands,exposed=sorted(exposed),contract_id=identity(commands,exposed))
    from micros_tooling.communication.protobuf import message_class
    for response in (False, True):
        message_class(descriptor(api, commands, response))  # Validate server descriptor bounds before building.
    from micros_tooling.config.protobuf import compile_text
    owner=Path(generated_directory)/'generated'
    for response in (False,True):
        direction='response' if response else 'request'
        schema=owner/f'{api}_rpc_{direction}.proto'
        content=proto(api,commands,response)
        service.setdefault('_generated_schemas', {})[str(schema)] = content
        compiled=compile_text(schema.name, content)
        require(compiled['maximum'] <= MAX_WIRE, f'{api} command {direction} needs {compiled["maximum"]} wire bytes; limit is {MAX_WIRE}')
        spec[direction+'_schema']=str(schema)
        if not exposed:continue
        port='rpc_'+direction
        require(port not in selection.get('subscriptions',{}) and port not in selection.get('publications',{}), 'rpc_request/rpc_response are reserved generated ports')
        used={c['key'] for c in channel_definitions.values()}
        key=next((k for k in range(1,33) if k not in used),None)
        require(key is not None and len(channel_definitions)<4, 'Command exposure exceeds the board channel limit (four)')
        alias=f'{api}_rpc_{direction}_{service["slot"]}'
        require(alias not in channel_definitions,'Generated command channel name collision')
        channel_definitions[alias]=dict(key=key,name=f'{service["name"]}.rpc.{direction}',interface=f'micros.commands.{api}.{direction}',major=1,minor=0,
                                       accepts_minor=[0,0],policy='stream',depth=4,max_payload=MAX_WIRE,schema=str(schema))
        selection.setdefault('publications' if response else 'subscriptions',{})[port]=dict(channel=alias)
        spec[direction+'_key']=key
    service['_commands']=spec
    service['sources'].append(str(owner/f'{api}_commands.c'))
    return spec


def bridge(recipe):
    exposed=[s for s in recipe['services'] if s.get('_commands',{}).get('exposed')]
    if not exposed:return
    from micros_tooling.config.repository import ROOT
    source=ROOT/'services/network-bridge'
    candidates=[s for s in recipe['services'] if Path(s['_interface']['source_directory'])==source]
    require(len(candidates)<=1, 'Use one network bridge per board for command exposure')
    if candidates:
        target=candidates[0]
        require(target['_interface']['name']=='bridge','Network bridge must use the bridge API')
    else:
        require(len(recipe['services'])<4,'Command exposure needs one network-bridge service slot (four service limit)')
        require(all(s['name']!='micros.command-bridge' for s in recipe['services']),'Reserved command bridge service name')
        directory=Path(exposed[0]['_interface']['directory']).parent/'command_bridge'
        from micros_tooling.config.declarations import contract as load_contract
        implementation = load_contract(source / 'service.toml')
        build = implementation['build']
        target=dict(name='micros.command-bridge', version=implementation['version'],
                    sources=[str(source / p) for p in build['sources']], defines=build.get('defines', []),
                    descriptor=build.get('descriptor', 'micros_descriptor'), arena='RAM', stack_bytes=2048,
                    slot=len(recipe['services']), capabilities=dict(implementation['capabilities'], handles=0), channels=[], schemas={},
                    _interface=dict(name=build['api'], directory=str(directory), source_directory=str(source), ports=[], gpio=[]))
        recipe['services'].append(target)
    for service in exposed:
        for port in ('rpc_request','rpc_response'):
            origin=next(p for p in service['_interface']['ports'] if p['name']==port)
            channel=next(c for c in service['channels'] if c['key']==origin['key'])
            alias=f'{service["_interface"]["name"]}_{service["slot"]}_{port}'
            require(not any(c['key']==channel['key'] for c in target['channels']),'Command port already bound on bridge')
            access='publish' if port=='rpc_request' else 'subscribe'
            target['_interface']['ports'].append(dict(origin,name=alias,access=access))
            target['channels'].append(dict(channel,access=access,schema=alias))
            target['schemas'][alias]=origin['schema']
            target['capabilities']['handles']+=1
    require(target['capabilities']['handles']<=MAX_HANDLES and len(target['schemas'])<=4,'Command bridge exceeds handle/schema budget')
