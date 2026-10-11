"""Published channel schemas for diagnostic readers; no presentation metadata."""
import base64
from pathlib import Path
from micros_tooling.storage.packages import require, canonical_json
from micros_tooling.communication.protobuf import message_class


def build(service):
    spec = service.get('_interface')
    if not spec: return []
    from micros_tooling.config.protobuf import compile_schema
    from google.protobuf import descriptor_pb2
    result = []
    commands = service.get('_commands') or {}
    reserved = {commands.get('request_key'), commands.get('response_key')}
    for port in spec['ports']:
        # Typed RPC owns its reply cursor; diagnostic readers must not drain it.
        if port['access'] != 'publish' or port['key'] in reserved: continue
        compiled = compile_schema(port['schema'])
        descriptors = descriptor_pb2.FileDescriptorSet.FromString(compiled['descriptor'])
        file = next(f for f in descriptors.file if f.name == Path(port['schema']).name)
        # Nanopb options affect native storage, not the wire message. The host
        # tools need no generator, imports, or service executable code.
        file.ClearField('dependency'); file.ClearField('options')
        def clean(message):
            message.ClearField('options')
            for field in message.field: field.ClearField('options')
            for nested in message.nested_type: clean(nested)
        for message in file.message_type: clean(message)
        result.append(dict(name=port['name'], key=port['key'], descriptor=base64.b64encode(file.SerializeToString()).decode()))
    validate(result, service.get('channels', []))
    return result


def validate(ports, channels):
    require(isinstance(ports, list) and len(ports) <= 32 and len(canonical_json(ports)) <= 131072, 'Invalid channel metadata')
    names = set()
    for port in ports:
        require(isinstance(port, dict) and port.keys() == {'name', 'key', 'descriptor'}, 'Invalid published port')
        require(isinstance(port['name'], str) and 0 < len(port['name']) <= 80 and port['name'] not in names, 'Invalid or duplicate port name')
        names.add(port['name'])
        require(type(port['key']) is int and 1 <= port['key'] <= 32 and any(c['key'] == port['key'] and c['access'] == 'publish' for c in channels), 'Port must publish a declared channel')
        message_class(port['descriptor'])


def bind(packages):
    ordered = sorted(packages, key=lambda p: (any(c['access']=='publish' for c in p['manifest']['channels']), p['manifest']['name']))
    result = []
    for package in ordered:
        m = package['manifest']
        for port in m.get('published_ports', []):
            origin = next(c for c in m['channels'] if c['key'] == port['key'] and c['access'] == 'publish')
            matches = [(i,c) for i,p in enumerate(ordered) if p['manifest'].get('ipc_bridge')
                       for c in p['manifest']['channels'] if c['key']==port['key'] and c['access']=='subscribe'
                       and p['manifest']['schemas'][c['schema']] == m['schemas'][origin['schema']]]
            if not matches: continue
            require(len(matches)==1, 'Published port has ambiguous bridge mapping')
            instance, channel = matches[0]
            result.append(dict(service=m['name'], version=m['version'], port=port, instance=instance, max_payload=channel['max_payload']))
    return result


def validate_bindings(bindings):
    require(isinstance(bindings,list) and len(bindings)<=128 and len(canonical_json(bindings))<=524288, 'Invalid channel bindings')
    ids=set()
    for b in bindings:
        require(isinstance(b,dict) and b.keys()=={'service','version','port','instance','max_payload'}, 'Invalid channel binding')
        require(all(isinstance(b[k],str) and 0<len(b[k])<=80 for k in ('service','version')), 'Invalid channel service')
        require(type(b['instance']) is int and 0<=b['instance']<4, 'Invalid bridge instance')
        require(type(b['max_payload']) is int and 1<=b['max_payload']<=256, 'Invalid channel payload bound')
        require(isinstance(b['port'], dict), 'Invalid published port')
        validate([b['port']], [dict(key=b['port'].get('key'), access='publish')])
        identity=(b['service'],b['port']['name'])
        require(identity not in ids,'Duplicate bound port');ids.add(identity)
