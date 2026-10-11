"""Shared, side-effect-free declaration validation and reference resolution.

Authored TOML is the authority. The dictionaries returned here are an internal
model, never a second configuration file for operators to maintain.
"""
import copy
import re
from pathlib import Path

from micros_tooling.storage.packages import require, integer, identifier, MAX_HANDLES, MAX_PAYLOAD, MAX_CHANNEL_DEPTH


def table(value, allowed, required=(), context='declaration'):
    require(isinstance(value, dict), f'{context}: expected a table')
    missing, extra = set(required) - value.keys(), value.keys() - set(allowed)
    require(not missing and not extra,
            f'{context}: ' + '; '.join(filter(None, [
                'missing ' + ', '.join(sorted(missing)) if missing else '',
                'unknown fields ' + ', '.join(sorted(extra)) if extra else ''])))


def field(spec, types=None, context='field'):
    """Resolve and validate a value type, independently of its use site/default."""
    types = types or {}
    if isinstance(spec, str):
        spec = copy.deepcopy(types.get(spec, {'type': spec}))
    require(isinstance(spec, dict), f'{context}: expected a type name or table')
    spec = copy.deepcopy(spec)
    kind = spec.get('type')
    require(isinstance(kind, str), f'{context}: type must be a name')
    if kind in types:
        table(spec, {'type'}, {'type'}, context)
        spec = copy.deepcopy(types[kind])
        kind = spec['type']
    if kind in ('uint32', 'sint32'):
        table(spec, {'type', 'min', 'max'}, {'type'}, context)
        low, high = (0, 2**32-1) if kind == 'uint32' else (-2**31, 2**31-1)
        require(type(spec.get('min', low)) is int and type(spec.get('max', high)) is int
                and low <= spec.get('min', low) <= spec.get('max', high) <= high,
                f'{context}: invalid {kind} bounds')
    elif kind == 'bool':
        table(spec, {'type'}, {'type'}, context)
    elif kind == 'string':
        table(spec, {'type', 'max_bytes'}, {'type', 'max_bytes'}, context)
        integer(spec['max_bytes'], 1, 64, f'{context}.max_bytes')
    elif kind == 'enum':
        from micros_tooling.config.configuration import valid_identifier
        table(spec, {'type', 'choices'}, {'type', 'choices'}, context)
        choices = spec['choices']
        require(isinstance(choices, list) and 1 <= len(choices) <= 32
                and all(valid_identifier(c) and c != 'count' for c in choices)
                and len(set(choices)) == len(choices), f'{context}: enums require unique choices')
    else:
        raise ValueError(f'{context}: unsupported or unknown type {kind!r}')
    return spec


def named_types(value, context='types'):
    table(value, set(value) if isinstance(value, dict) else (), context=context)
    require(len(value) <= 32, f'{context}: at most 32 named types')
    result = {}
    for name, spec in value.items():
        require(isinstance(name, str) and re.fullmatch('[A-Z][A-Za-z0-9]*', name),
                f'{context}.{name}: named types use UpperCamelCase')
        result[name] = field(spec, context=f'{context}.{name}')
    return result


def type_reference(spec, types):
    name = spec if isinstance(spec, str) else spec.get('type') if isinstance(spec, dict) else None
    return name if isinstance(name, str) and name in types else None


def interface(path):
    from micros_tooling.config.configuration import read_toml
    path = Path(path).resolve()
    document = read_toml(path)
    table(document, {'interface', 'delivery'}, {'interface'}, str(path))
    value = document['interface']
    modern = 'delivery' in document
    table(value, {'interface', 'schema', 'max_payload'} if modern else
          {'name', 'interface', 'major', 'minor', 'schema', 'accepts_minor', 'max_payload'},
          {'interface', 'schema'} if modern else {'interface', 'major', 'minor', 'schema'}, str(path))
    # ABI version fields remain internal for existing package readers. Authored
    # interfaces use exact protobuf compatibility, not hand-maintained versions.
    value.setdefault('major', 0)
    value.setdefault('minor', 0)
    identifier(value['interface'], f'{path}: interface.interface')
    for key in ('major', 'minor'):
        integer(value[key], 0, 65535, f'{path}: interface.{key}')
    require(isinstance(value['schema'], str), f'{path}: interface.schema must be a path')
    schema = (path.parent / value['schema']).resolve()
    from micros_tooling.config.protobuf import compile_schema
    compiled = compile_schema(schema)
    if 'max_payload' in value:
        integer(value['max_payload'], compiled['maximum'], MAX_PAYLOAD, f'{path}: max_payload')
    accepted = value.get('accepts_minor', [value['minor'], value['minor']])
    require(isinstance(accepted, list) and len(accepted) == 2 and all(type(n) is int for n in accepted)
            and 0 <= accepted[0] <= value['minor'] <= accepted[1] <= 65535, f'{path}: invalid accepts_minor')
    result = dict(interface=value['interface'], major=value['major'], minor=value['minor'],
                accepts_minor=accepted, schema=str(schema), max_payload=value.get('max_payload', compiled['maximum']))
    if modern:
        delivery = document['delivery']
        table(delivery, {'policy', 'kind'}, {'policy'}, f'{path}: delivery')
        require(delivery['policy'] in ('stream', 'latest'), f'{path}: invalid delivery.policy')
        require(delivery.get('kind') in (None, 'state', 'event', 'action'), f'{path}: invalid delivery.kind')
        require(not delivery.get('kind') or (delivery['policy'] == 'latest' and result['max_payload'] <= 64),
                f'{path}: coordination requires latest and payload <=64')
        result.update(delivery, _delivery=True)
    return result


def _contract(path):
    from micros_tooling.config.configuration import read_toml
    return normalize_contract(read_toml(path), path)


def normalize_contract(document, path):
    """Validate an authored frontend's document into the shared internal model."""
    from micros_tooling.config.configuration import read_toml, valid_identifier, fields_for
    path = Path(path).resolve()
    table(document, {'service'}, {'service'}, str(path))
    value = copy.deepcopy(document['service'])
    context = f'{path}: service'
    table(value, {'name', 'version', 'build', 'capabilities', 'config_schema', 'hardware', 'config', 'pins',
                  'subscriptions', 'publications', 'commands', 'types', 'timers'},
          {'name', 'version', 'build'}, context)
    config_label = 'config' if 'config' in value else 'config_schema'
    for name, spec in value.get('hardware', {}).items() if isinstance(value.get('hardware', {}), dict) else ():
        table(spec, {'direction', 'fixed_pin'}, {'direction'}, f'{context}.hardware.{name}')
    if 'config' in value:
        require('config_schema' not in value, context + ': use config only; config_schema duplicates the declaration')
        value['config_schema'] = value.pop('config')
    if 'pins' in value:
        require('hardware' not in value, context + ': use pins only; hardware duplicates the declaration')
        pins = value.pop('pins')
        require(isinstance(pins, dict), context + '.pins: expected a named map')
        hardware = value['hardware'] = {}
        for name, spec in pins.items():
            label = f'{context}.pins.{name}'
            table(spec, {'type', 'fixed_pin'}, {'type'}, label)
            require(spec['type'] in ('input', 'pullup', 'pulldown', 'output', 'analog'), label + ': invalid pin type')
            hardware[name] = dict(direction='output' if spec['type'] == 'output' else 'input',
                                  _type=spec['type'])
            if 'fixed_pin' in spec: hardware[name]['fixed_pin'] = spec['fixed_pin']
    identifier(value['name'], context + '.name')
    require(isinstance(value['version'], str) and re.fullmatch(r'\d+\.\d+\.\d+', value['version']),
            context + '.version: expected major.minor.patch')
    build = value['build']
    table(build, {'sources', 'defines', 'descriptor', 'api', 'lifecycle'}, {'sources', 'api'}, context + '.build')
    require(valid_identifier(build['api']), context + '.build.api: expected a C identifier')
    require(isinstance(build['sources'], list) and build['sources']
            and all(isinstance(s, str) and s for s in build['sources']), context + '.build.sources: expected source paths')
    require(isinstance(build.get('defines', []), list) and all(isinstance(d, str) for d in build.get('defines', [])),
            context + '.build.defines: expected strings')
    require(valid_identifier(build.get('descriptor', 'micros_descriptor')), context + '.build.descriptor: invalid symbol')
    require(build.get('lifecycle', 'manual') in ('manual', 'hooks'), context + '.build.lifecycle: expected manual or hooks')
    declared_types = value.get('types', {})
    if isinstance(declared_types, str):
        types_path = (path.parent / declared_types).resolve()
        require(types_path.is_relative_to(path.parent),
                context + '.types: types file must remain inside this service directory; '
                'declare types in service.toml or a service-local types.toml')
        library = read_toml(types_path)
        table(library, {'types'}, {'types'}, str(types_path))
        declared_types = library['types']
        try:
            types = value['types'] = named_types(declared_types, str(types_path) + ': types')
        except ValueError as error:
            from micros_tooling.config.diagnostics import located
            raise located(types_path, error) from error
    else:
        types = value['types'] = named_types(declared_types, context + '.types')
    refs = value['_type_refs'] = {'config': {}, 'commands': {}}
    settings = value.setdefault('config_schema', {})
    require(isinstance(settings, dict), f'{context}.{config_label}: expected a table')
    for name, spec in settings.items():
        require(isinstance(spec, dict) and 'default' in spec, f'{context}.{config_label}.{name}: missing default')
        ref = type_reference(spec, types)
        if ref: refs['config'][name] = ref
        settings[name] = dict(field({k:v for k,v in spec.items() if k != 'default'}, types,
                                    f'{context}.{config_label}.{name}'), default=spec['default'])
    if settings: fields_for(build['api'], {'fields': settings})
    hardware = value.setdefault('hardware', {})
    require(isinstance(hardware, dict), context + '.hardware: expected a table')
    for name, spec in hardware.items():
        require(valid_identifier(name), f'{context}.hardware.{name}: invalid role')
        table(spec, {'direction', 'fixed_pin', '_type'}, {'direction'}, f'{context}.hardware.{name}')
        require(spec['direction'] in ('input', 'output'), f'{context}.hardware.{name}: invalid direction')
        if 'fixed_pin' in spec: integer(spec['fixed_pin'], 0, 39, f'{context}.hardware.{name}.fixed_pin')
    capabilities = value.setdefault('capabilities', {})
    table(capabilities, {'gpio', 'timers'}, context=context + '.capabilities')
    if 'gpio' in capabilities:
        require(isinstance(capabilities['gpio'], list) and all(valid_identifier(g) for g in capabilities['gpio']) and len(set(capabilities['gpio'])) == len(capabilities['gpio'])
                and set(capabilities['gpio']) == set(hardware), context + ': hardware must describe every logical GPIO')
    else: capabilities['gpio'] = list(hardware)
    timers = value.get('timers', {})
    if isinstance(timers, list):
        require(all(valid_identifier(t) for t in timers) and len(set(timers)) == len(timers),
                context + '.timers: expected unique timer names')
        timers = value['timers'] = {name: {} for name in timers}
    require(isinstance(timers, dict), context + '.timers: expected named timer tables')
    for name, spec in timers.items():
        require(valid_identifier(name), f'{context}.timers.{name}: invalid timer name')
        table(spec, set(), context=f'{context}.timers.{name}')
    require(not timers or 'timers' not in capabilities, context + ': named timers replace capabilities.timers')
    capabilities.setdefault('timers', len(timers))
    integer(capabilities['timers'], 0, MAX_HANDLES, context + '.capabilities.timers')
    seen = set()
    for direction in ('subscriptions', 'publications'):
        ports = value.setdefault(direction, {})
        require(isinstance(ports, dict), f'{context}.{direction}: expected a table')
        for name, spec in ports.items():
            require(isinstance(spec, dict), f'{context}.{direction}.{name}: expected a table')
            label = f'{context}.{direction}.{name}'
            require(valid_identifier(name) and name not in seen, label + ': invalid or duplicate port')
            seen.add(name)
            if isinstance(spec.get('interface'), str) and spec['interface'].endswith('.toml'):
                table(spec, {'interface', 'policy', 'min_depth', 'accepts_minor', 'kind'}, {'interface'}, label)
                require(isinstance(spec['interface'], str), label + ': interface must be a path')
                resolved = interface(path.parent / spec['interface'])
                if resolved.pop('_delivery', False):
                    for key in ('policy', 'kind', 'accepts_minor'):
                        # Read old declarations during migration, but never allow
                        # an override of the authoritative interface semantics.
                        require(key not in spec or spec[key] == resolved.get(key),
                                label + ': ' + key + ' belongs to the shared interface')
                else:
                    require('policy' in spec, label + ': missing policy (legacy interface has no delivery declaration)')
                spec = ports[name] = dict(resolved, **{k:v for k,v in spec.items() if k != 'interface'},
                                         _reference=str((path.parent / spec['interface']).resolve()))
                spec.setdefault('accepts_minor', [spec['minor'], spec['minor']])
                spec['depth'] = spec.get('min_depth', 1)
            else:
                required = {'interface', 'major', 'minor', 'accepts_minor', 'schema', 'policy', 'depth', 'max_payload'}
                table(spec, required | {'kind'}, required, label)
                require(isinstance(spec['schema'], str), label + ': schema must be a path')
                spec['schema'] = str((path.parent / spec['schema']).resolve())
            require(isinstance(spec['interface'], str) and spec['interface'], label + ': invalid interface')
            for key in ('major', 'minor'): integer(spec[key], 0, 65535, label + '.' + key)
            accepted = spec['accepts_minor']
            require(isinstance(accepted, list) and len(accepted) == 2 and all(type(v) is int for v in accepted)
                    and 0 <= accepted[0] <= spec['minor'] <= accepted[1] <= 65535, label + ': invalid accepts_minor')
            integer(spec['depth'], 1, MAX_CHANNEL_DEPTH, label + '.depth')
            integer(spec['max_payload'], 1, MAX_PAYLOAD, label + '.max_payload')
            require(spec['policy'] in ('stream', 'latest') and (spec['policy'] != 'latest' or spec['depth'] == 1), label + ': invalid policy/depth')
            require(spec.get('kind') in (None, 'state', 'action', 'event'), label + ': invalid coordination kind')
    require(isinstance(value.get('commands', {}), dict), context + '.commands: expected a table')
    if value.get('commands'):
        from micros_tooling.commands.schema import normalize
        normalized = normalize(value['commands'], types)
        for name, command in value['commands'].items():
            refs['commands'][name] = {direction: {key: type_reference(spec, types) for key, spec in command.get(direction, {}).items()
                                                 if type_reference(spec, types)} for direction in ('args', 'returns')}
        value['commands'] = normalized
        require(not seen & {'rpc_request', 'rpc_response'}, context + ': rpc_request/rpc_response are reserved command ports')
    from micros_tooling.config.type_generation import c_name
    reserved_types = {'config', 'context', 'state', 'commands'}
    reserved_types.update(name + '_message' for name in seen)
    reserved_types.update(name + '_' + direction for name in value.get('commands', {}) for direction in ('request', 'response'))
    for name, spec in types.items():
        suffix = c_name('', name).lstrip('_')
        require(suffix not in reserved_types, f'{context}.types.{name}: C name collides with a generated service type; rename this type')
        operations = ('name', 'valid') if spec['type'] == 'enum' else ('valid',) if spec['type'] in ('uint32', 'sint32') else ()
        require(not any(suffix + '_' + operation in value.get('commands', {}) for operation in operations),
                f'{context}.types.{name}: generated type helper collides with a command name')
    if build.get('lifecycle') == 'hooks':
        from micros_tooling.config.service_hooks import hooks
        ports = [dict(name=name, access=access, kind=spec.get('kind'))
                 for direction, access in (('subscriptions', 'subscribe'), ('publications', 'publish'))
                 for name, spec in value[direction].items()]
        require(not any(p['kind'] for p in ports),
                context + ': hook lifecycle supports ordinary ports; coordination ports require the manual coordination adapter')
        hooks(build['api'], ports, value.get('commands'), refs['commands'])
    # A standalone service must fit its declared resources even before exposure.
    handles = capabilities['timers'] + len(hardware) + len(seen)
    require(handles <= MAX_HANDLES, f'{context}: resources require {handles} handles; limit is {MAX_HANDLES}')
    return value


def contract(path):
    from micros_tooling.config.diagnostics import located
    try:
        return _contract(path)
    except ValueError as error:
        raise located(path, error) from error
