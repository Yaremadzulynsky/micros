"""Package and bind command contracts to the exact deployed graph."""
from .schema import normalize, identity, proto
from micros_tooling.storage.packages import require, canonical_json, canonical_schema


def build(service):
    spec=service.get('_commands')
    if not spec or not spec['exposed']:return None
    return dict(format=2,**{k:spec[k] for k in ('api','commands','exposed','contract_id','request_key','response_key')})


def validate(value, channels=None, schemas=None):
    from micros_tooling.config.configuration import valid_identifier
    require(isinstance(value,dict) and value.keys()=={'format','api','commands','exposed','contract_id','request_key','response_key'}, 'Invalid command metadata')
    require(type(value['format']) is int and value['format'] in (1, 2) and valid_identifier(value['api']), 'Unsupported command metadata format/API')
    require(len(canonical_json(value))<=32768, 'Command metadata exceeds 32 KiB')
    commands=normalize(value['commands'])
    require(commands==value['commands'], 'Command metadata must contain normalized fields')
    exposed=value['exposed']
    require(isinstance(exposed,list) and exposed and all(isinstance(c,str) and c in commands for c in exposed)
            and exposed==sorted(set(exposed)), 'Invalid exposed command list')
    require(type(value['contract_id']) is int and value['contract_id']==identity(commands,exposed,format=value['format']), 'Command contract identity mismatch')
    require(value['request_key']!=value['response_key'], 'Command request/reply keys must differ')
    for direction,access in [('request','subscribe'),('response','publish')]:
        key=value[direction+'_key']
        require(type(key) is int and 1<=key<=32, 'Invalid command channel key')
        if channels is not None:
            matches=[c for c in channels if c['key']==key and c['access']==access]
            require(len(matches)==1 and matches[0]['policy']=='stream' and matches[0]['depth']==4
                    and matches[0]['max_payload']==112, 'Invalid command channel binding')
            if schemas is not None:
                require(canonical_schema(schemas[matches[0]['schema']])==canonical_schema(proto(value['api'],commands,direction=='response').encode()), 'Command schema differs from generated declaration')


def bind(packages):
    ordered=sorted(packages,key=lambda p:(any(c['access']=='publish' for c in p['manifest']['channels']),p['manifest']['name']))
    result=[]
    for service_index,package in enumerate(ordered):
        manifest=package['manifest']; spec=manifest.get('commands')
        if spec is None:continue
        validate(spec)
        instances=[]
        for direction,access in [('request','publish'),('response','subscribe')]:
            key=spec[direction+'_key']
            origin=next(c for c in manifest['channels'] if c['key']==key)
            matches=[i for i,p in enumerate(ordered) if p['manifest'].get('ipc_bridge')
                     for c in p['manifest']['channels'] if c['key']==key and c['access']==access
                     and p['manifest']['schemas'][c['schema']]==manifest['schemas'][origin['schema']]]
            require(len(matches)==1,'Commands require one matching bridge for request and reply')
            instances.append(matches[0])
        require(instances[0]==instances[1],'Command request/reply must use the same bridge')
        result.append(dict(service=manifest['name'],version=manifest['version'],service_index=service_index,instance=instances[0],contract=spec))
    return result


def validate_bindings(bindings):
    require(isinstance(bindings,list) and len(bindings)<=4 and len(canonical_json(bindings))<=131072,'Invalid command bindings')
    seen=set()
    for binding in bindings:
        require(isinstance(binding,dict) and binding.keys()=={'service','version','service_index','instance','contract'}, 'Invalid bound command service')
        require(all(isinstance(binding[k],str) and 0<len(binding[k])<=80 for k in ('service','version')),'Invalid command service name')
        require(binding['service'] not in seen,'Duplicate command service');seen.add(binding['service'])
        require(all(type(binding[k]) is int and 0<=binding[k]<4 for k in ('instance','service_index')),'Invalid command instance')
        validate(binding['contract'])
