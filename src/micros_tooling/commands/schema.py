"""One command declaration drives native interfaces, protobuf and remote validation."""
import hashlib
import re
from micros_tooling.storage.packages import require, canonical_json

MAX_COMMANDS = 8
MAX_WIRE = 112  # Fits IPC WRITE's 255 ASCII bytes, including instance/key and hex.
RESERVED = {'request_id', 'contract_id', 'result', 'command', 'rpc_request', 'rpc_response', 'commands_open', 'commands_step', 'commands_close'}


def name(value):
    from micros_tooling.config.configuration import valid_identifier
    return isinstance(value, str) and len(value) <= 48 and valid_identifier(value) and value not in RESERVED


def normalize(commands, types=None):
    from micros_tooling.config.declarations import named_types, field
    types = named_types({} if types is None else types)
    require(isinstance(commands, dict) and 1 <= len(commands) <= MAX_COMMANDS, 'Declare one to eight commands')
    def fields(source):
        require(isinstance(source, dict) and len(source) <= 8, 'Command args/returns must contain at most eight fields')
        result = {}
        for key, original in sorted(source.items()):
            require(name(key), 'Invalid command field: ' + str(key))
            spec = field(original, types, 'command field ' + key)
            if spec['type'] in ('uint32', 'sint32'):
                low, high = (0, 2**32-1) if spec['type'] == 'uint32' else (-2**31, 2**31-1)
                spec = dict(type=spec['type'], min=spec.get('min', low), max=spec.get('max', high))
            if spec['type'] == 'enum':
                require(all(name(c) for c in spec['choices']), 'Invalid enum choice')
            result[key] = spec
        return result
    normalized = {}
    for command, spec in sorted(commands.items()):
        require(name(command), 'Invalid command name: ' + str(command))
        require(isinstance(spec,dict) and spec.keys() <= {'description','args','returns'}, 'Unknown command option')
        description = spec.get('description',command.replace('_',' '))
        require(isinstance(description,str) and 0 < len(description) <= 80, 'Command description must be 1..80 characters')
        normalized[command] = dict(description=description,args=fields(spec.get('args',{})),returns=fields(spec.get('returns',{})))
    return normalized


def identity(commands, exposed, *, format=2):
    if format >= 2:
        commands = {name: {k:v for k,v in spec.items() if k != "description"} for name, spec in commands.items()}
    return int.from_bytes(hashlib.sha256(canonical_json(dict(commands=commands,exposed=sorted(exposed)))).digest()[:4],'little') or 1


def message_name(command):
    return 'Command_' + command


def proto(api, commands, response=False):
    direction = 'Response' if response else 'Request'
    lines = ['// Generated from service command declarations; do not edit.', 'syntax = "proto3";', f'package micros.commands.{api};', 'import "nanopb.proto";',
             f'message {direction} {{', '  fixed64 request_id = 1;', '  fixed32 contract_id = 2;']
    if response:
        lines.append('  sint32 result = 3;')
    for command, spec in commands.items():
        lines.append(f'  message {message_name(command)} {{')
        for index,(field,value) in enumerate(spec['returns' if response else 'args'].items(),1):
            kind = 'uint32' if value['type']=='enum' else value['type']
            options = f' [(nanopb).max_size = {value["max_bytes"]+1}]' if kind=='string' else ''
            lines.append(f'    {kind} {field} = {index}{options};')
        lines.append('  }')
    lines.append('  oneof command {')
    for index, command in enumerate(commands,10):
        lines.append(f'    {message_name(command)} {command} = {index};')
    return '\n'.join(lines+['  }','}',''])


def descriptor(api, commands, response=False):
    """Construct the wire descriptor without protoc; usable by the management server."""
    import base64
    from google.protobuf import descriptor_pb2
    direction = 'Response' if response else 'Request'
    file = descriptor_pb2.FileDescriptorProto(name=f'{api}_rpc_{direction.lower()}.proto',package=f'micros.commands.{api}',syntax='proto3')
    m = file.message_type.add(name=direction)
    m.field.add(name='request_id',number=1,type=6,label=1)
    m.field.add(name='contract_id',number=2,type=7,label=1)
    if response: m.field.add(name='result',number=3,type=17,label=1)
    m.oneof_decl.add(name='command')
    for tag,(command,spec) in enumerate(commands.items(),10):
        nested = m.nested_type.add(name=message_name(command))
        for number,(field,value) in enumerate(spec['returns' if response else 'args'].items(),1):
            nested.field.add(name=field,number=number,type={'uint32':13,'enum':13,'sint32':17,'bool':8,'string':9}[value['type']],label=1)
        m.field.add(name=command,number=tag,type=11,label=1,oneof_index=0,type_name=f'.{file.package}.{direction}.{nested.name}')
    return base64.b64encode(file.SerializeToString()).decode()


def values(fields, supplied, *, decode=False):
    require(isinstance(supplied,dict) and supplied.keys()==fields.keys(), 'Command fields must match the declaration exactly')
    result={}
    for key,spec in fields.items():
        value=supplied[key];kind=spec['type']
        if kind=='enum':
            if decode:
                require(type(value) is int and 0<=value<len(spec['choices']), 'Invalid enum response')
                value=spec['choices'][value]
            else:
                require(isinstance(value,str) and value in spec['choices'], f"{key}: expected one of {', '.join(spec['choices'])}")
                value=spec['choices'].index(value)
        elif kind=='string':
            require(isinstance(value,str) and '\0' not in value and len(value.encode('utf-8'))<=spec['max_bytes'], f'{key}: invalid or oversized string')
        elif kind=='bool':
            require(type(value) is bool, f'{key}: expected true or false')
        else:
            require(type(value) is int and spec['min']<=value<=spec['max'], f"{key}: expected {spec['min']}..{spec['max']}")
        result[key]=value
    return result


def parse_arguments(fields, supplied):
    require(supplied.keys()==fields.keys(), 'Supply exactly the fields shown by help call SERVICE COMMAND.')
    result={}
    for key,value in supplied.items():
        kind=fields[key]['type']
        if kind in ('uint32','sint32'):
            try: value=int(value)
            except ValueError: raise ValueError(f'{key}: expected an integer') from None
        elif kind=='bool':
            require(value in ('true','false','0','1'), f'{key}: expected true or false')
            value=value in ('true','1')
        result[key]=value
    values(fields,result)
    return result


def describe(spec):
    kind=spec['type']
    if kind=='enum':return ' | '.join(spec['choices'])
    if kind=='string':return f'text, at most {spec["max_bytes"]} bytes'
    if kind=='bool':return 'true | false'
    return f'{spec["min"]}..{spec["max"]}'
