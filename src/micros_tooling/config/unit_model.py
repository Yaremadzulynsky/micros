"""Resolve unit choices against service requirements without writing artifacts."""
from pathlib import Path
from micros_tooling.storage.packages import require, canonical_schema, integer, identifier, MAX_CHANNEL_DEPTH, MAX_PAYLOAD


def contracts(root, path):
    from micros_tooling.config.declarations import contract
    result = {}
    for alias, selection in root.get('services', {}).items():
        if isinstance(selection, dict) and 'contract' in selection:
            require(isinstance(selection.get('source'), str) and isinstance(selection['contract'], str),
                    f'{path}: services.{alias}: source and contract must be paths')
            location = (Path(path).parent / selection['source'] / selection['contract']).resolve()
            result[alias] = (location, contract(location))
    return result


def gpio_directions(root, models):
    from collections import Counter
    roles = Counter(role for alias, (_, model) in models.items()
                    if root['services'][alias].get('enabled', True) for role in model['hardware'])
    for alias, (_, model) in models.items():
        selection = root['services'][alias]
        if not selection.get('enabled', True): continue
        if 'pins' in selection:
            require('gpio_bindings' not in selection, f'{alias}: use pins only, not gpio_bindings')
            pins = selection.pop('pins')
            require(isinstance(pins, dict) and set(pins) == set(model['hardware']),
                    f'{alias}.pins: assign exactly the declared service pins')
            bindings = selection['gpio_bindings'] = {}
            for role, pin in pins.items():
                integer(pin, 0, 255, f'{alias}.pins.{role}')
                bindings[role] = dict(pin=pin)
                if roles[role] > 1 or role in root.get('board', {}).get('gpio', {}):
                    bindings[role]['name'] = alias + '_' + role
        for role, binding in selection.get('gpio_bindings', {}).items():
            if isinstance(binding, dict) and role in model['hardware']:
                binding.setdefault('direction', model['hardware'][role]['direction'])
                pin_type = model['hardware'][role].get('_type')
                if pin_type:
                    from micros_tooling.config.chips import resolve_pin_type
                    board = root.get('board', {})
                    pull = resolve_pin_type(board, binding.get('pin'), pin_type, f'{alias}.pins.{role}')
                    require('pull' not in binding or binding['pull'] == pull,
                            f'{alias}.{role}: pull conflicts with the service pin requirement')
                    binding['pull'] = pull


def channels(root, path, models):
    declarations = root.setdefault('channels', {})
    require(isinstance(declarations, dict), f'{path}: channels must be a named map')
    # Legacy units with explicit numeric keys remain readable. New units use
    # name-based attachment exclusively, including services with no pins.
    named = not any(isinstance(c, dict) and 'key' in c for c in declarations.values())
    endpoints = {}
    for alias, (location, model) in models.items():
        selection = root['services'][alias]
        if not selection.get('enabled', True): continue
        for direction in ('subscriptions', 'publications'):
            if named:
                require(direction not in selection,
                        f'{path}: services.{alias}.{direction}: channel membership comes from matching service port names; remove bindings')
                selection[direction] = {port: dict(channel=port) for port in model[direction]}
            for port, binding in selection.get(direction, {}).items():
                expected = model[direction].get(port)
                if not expected or not isinstance(binding, dict) or 'channel' not in binding: continue
                binding.setdefault('kind', expected.get('kind'))
                if binding['kind'] is None: del binding['kind']
                endpoints.setdefault(binding['channel'], []).append((location, direction, expected))
    for name in endpoints:
        require(name in declarations, f'{path}: required channel {name!r} is not declared')
    if named:
        from micros_tooling.config.declarations import table
        require(len(declarations) <= 32, f'{path}: at most 32 channels')
        for key, name in enumerate(sorted(declarations), 1):
            channel = declarations[name]
            table(channel, {'depth'}, context=f'{path}: channels.{name}')
            require(name in endpoints, f'{path}: channels.{name}: no enabled service port defines its contract')
            channel.update(key=key, name=name)
    for name, connected in endpoints.items():
        if name not in declarations: continue  # The binding validator provides context.
        channel = declarations[name]
        require(isinstance(channel, dict), f'{path}: channels.{name}: expected a table')
        modern = [e for e in connected if '_reference' in e[2]]
        if not modern: continue
        require(len(modern) == len(connected), f'{path}: channels.{name}: migrate all connected ports to shared interface references together')
        fields = {'interface', 'major', 'minor', 'accepts_minor', 'schema'}
        require(not (fields & channel.keys()),
                f'{path}: channels.{name}: interface metadata belongs to the referenced interface; remove {sorted(fields & channel.keys())}')
        expected = modern[0][2]
        for location, direction, spec in modern[1:]:
            require((spec['interface'], spec['major'], spec['minor']) == (expected['interface'], expected['major'], expected['minor'])
                    and canonical_schema(Path(spec['schema']).read_bytes()) == canonical_schema(Path(expected['schema']).read_bytes()),
                    f'{path}: channels.{name}: conflicting interface references, including {location}; exact schema compatibility is required')
        policies = {e[2]['policy'] for e in modern}
        require(len(policies) == 1, f'{path}: channels.{name}: connected services require incompatible delivery policies {sorted(policies)}')
        policy = next(iter(policies))
        require('policy' not in channel or channel['policy'] == policy,
                f'{path}: channels.{name}: selected policy {channel.get("policy")!r}; services require {policy!r}')
        channel.setdefault('policy', policy)
        kinds = {e[2].get('kind') for e in modern}
        require(len(kinds) == 1, f'{path}: channels.{name}: incompatible communication kinds')
        channel.setdefault('depth', max(e[2]['depth'] for e in modern))
        require(type(channel['depth']) is int and channel['depth'] >= max(e[2]['depth'] for e in modern),
                f'{path}: channels.{name}.depth must be at least {max(e[2]["depth"] for e in modern)}')
        channel.setdefault('max_payload', max(e[2]['max_payload'] for e in modern))
        for field in fields: channel[field] = expected[field]
    used = set()
    from micros_tooling.config.declarations import table
    required = {'name', 'key', 'interface', 'major', 'minor', 'accepts_minor', 'schema', 'policy', 'depth', 'max_payload'}
    for name, channel in declarations.items():
        context = f'{path}: channels.{name}'
        partial = not models and 'unit' not in root and not required <= channel.keys()
        table(channel, required, {'key', 'schema', 'max_payload'} if partial else required, context)
        key = integer(channel['key'], 1, 32, context + '.key')
        require(key not in used, context + ': duplicate channel key')
        used.add(key)
        if 'name' in channel: identifier(channel['name'], context + '.name')
        if 'interface' in channel: identifier(channel['interface'], context + '.interface')
        if 'depth' in channel: integer(channel['depth'], 1, MAX_CHANNEL_DEPTH, context + '.depth')
        integer(channel['max_payload'], 1, MAX_PAYLOAD, context + '.max_payload')
        for field in ('major', 'minor'):
            if field in channel: integer(channel[field], 0, 65535, context + '.' + field)
        accepted = channel.get('accepts_minor', [channel.get('minor', 0)] * 2)
        require(isinstance(accepted, list) and len(accepted) == 2 and all(type(n) is int for n in accepted)
                and 0 <= accepted[0] <= channel.get('minor', 0) <= accepted[1] <= 65535, context + ': invalid accepts_minor')
        require(channel.get('policy', 'latest') in ('latest', 'stream') and (channel.get('policy', 'latest') != 'latest' or channel.get('depth', 1) == 1),
                context + ': invalid policy/depth')
        require(isinstance(channel['schema'], str), context + '.schema must be a path')
