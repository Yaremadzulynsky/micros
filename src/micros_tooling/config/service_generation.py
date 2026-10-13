"""Service-owned interfaces and separate, unit-owned link adapters.

Only the contract and its schemas enter service generation. A board build links
one binding implementation to that interface; no board selection is needed to
edit, generate, or compile service sources.
"""
from pathlib import Path
from micros_tooling.storage.packages import require
from micros_tooling.config.configuration import config_artifacts
from micros_tooling.config.protobuf import compile_schema, compile_text
from micros_tooling.config.interfaces import ipc_artifacts
from micros_tooling.commands.schema import proto, MAX_WIRE


def contract_path(path):
    path = Path(path).resolve()
    return path / 'service.toml' if path.is_dir() else path


def definition(path, model=None):
    """Project the validated service model into generator inputs, without fake units."""
    from micros_tooling.config.declarations import contract as load_contract
    path = contract_path(path)
    contract = model if model is not None else load_contract(path)
    api = contract['build']['api']
    hardware = contract['hardware']
    logical = [dict(name=g, direction=hardware[g]['direction'], pin=hardware[g].get('fixed_pin', 0), line=i)
               for i, g in enumerate(contract['capabilities']['gpio'])]
    ports = []
    for table, access in [('subscriptions', 'subscribe'), ('publications', 'publish')]:
        for port, spec in contract[table].items():
            ports.append(dict(name=port, access=access, key=len(ports)+1, schema=spec['schema'],
                              max_payload=spec['max_payload'], kind=spec.get('kind')))
    return path, contract, api, logical, ports, contract.get('commands') or None


def artifacts(path, output, model=None):
    path, contract, api, gpio, ports, commands = definition(path, model)
    output = Path(output).resolve()
    from micros_tooling.config.type_generation import artifacts as type_artifacts, configuration as typed_config
    files = {api + '_types.h': type_artifacts(api, contract['types'])} if contract['types'] else {}
    if contract["build"].get("lifecycle") == "hooks":
        from micros_tooling.config.service_hooks import artifacts
        files.update(artifacts(path, contract, api, gpio, ports, commands))
    planned_schemas = {}
    if commands:
        for response in (False, True):
            direction = 'response' if response else 'request'
            schema = output / f'{api}_rpc_{direction}.proto'
            files[schema.name] = proto(api, commands, response)
            planned_schemas[str(schema)] = files[schema.name]
            ports.append(dict(name='rpc_'+direction, access='publish' if response else 'subscribe',
                              key=len(ports)+1, schema=str(schema), max_payload=MAX_WIRE, kind=None))
        from micros_tooling.commands.generate import artifacts
        header, source = artifacts(dict(api=api, commands=commands, independent=True, type_refs=contract['_type_refs']['commands']))
        files[api+'_commands.h'] = header
        files[api+'_commands.c'] = source
    protocols = {}
    for port in ports:
        schema = Path(port['schema'])
        compiled = compile_text(schema.name, planned_schemas[str(schema)]) if str(schema) in planned_schemas else compile_schema(schema)
        protocols[port['schema']] = compiled
        for filename, content in compiled['files'].items():
            require(filename not in files or files[filename] == content, 'Conflicting service schemas: '+filename)
            files[filename] = content
    header, source = ipc_artifacts(dict(name=api, directory=str(output.parent), ports=ports, independent=True), protocols)
    files[api+'_ipc.h'], files[api+'_ipc.c'] = header, source
    fields = contract['config_schema']
    if fields: files[api+'_config.h'] = typed_config(config_artifacts(api, dict(name=api, fields=fields), {})[0], api, contract['_type_refs']['config'])
    resources = [f'/* Generated from {api} service hardware requirements. */', f'#ifndef {api.upper()}_RESOURCES_H',
                 f'#define {api.upper()}_RESOURCES_H', '#include <micros/service.h>']
    bindings = [f'/* Generated from {api} logical binding interface. Implemented by the unit adapter. */',
                f'#ifndef {api.upper()}_BINDINGS_H', f'#define {api.upper()}_BINDINGS_H', '#include <micros/service.h>', '#include <stdbool.h>']
    for port in ports: bindings.append(f'uint32_t {api}_{port["name"]}_binding(void);')
    for resource in gpio:
        prefix = api+'_'+resource['name']
        resources += [f'micros_result_t {prefix}_open(const micros_service_args_t *, micros_handle_t *);',
                      f'uint32_t {prefix}_pin(void);',
                      f'#define {prefix.upper()}_GPIO_PIN ' + (str(contract['hardware'][resource['name']]['fixed_pin'])+'u' if 'fixed_pin' in contract['hardware'][resource['name']] else f'({prefix}_pin())')]
        bindings.append(f'uint32_t {prefix}_binding(void);')
        kind = contract['hardware'][resource['name']].get('_type')
        if kind:
            operation = 'write' if kind == 'output' else 'read'
            parameter = 'uint32_t value' if kind == 'output' else 'uint32_t *value'
            resources.append(f'micros_result_t {prefix}_{operation}(const micros_service_args_t *, micros_handle_t, {parameter});')
    if contract['build'].get('lifecycle') != 'hooks':
        for timer in contract.get('timers', {}):
            resources += [f'/** Open the named {timer} timer; periods are microseconds. Close with timer_close. */',
                f'static inline micros_result_t {api}_timer_{timer}_open(const micros_service_args_t *a, uint64_t delay_us, uint64_t period_us, micros_timer_callback_t callback, void *user_data, micros_handle_t *handle) {{',
                '    if (!a || !a->api || !a->api->timer_open) return MICROS_ERROR_UNSUPPORTED;',
                '    return a->api->timer_open(a->context, delay_us, period_us, callback, user_data, handle);', '}']
    resources += [f'#define {api.upper()}_GPIO_COUNT {len(gpio)}u', '#endif', '']
    if commands:
        bindings += [f'uint32_t {api}_commands_contract(void);', f'bool {api}_commands_exposed(uint32_t tag);']
    bindings += ['#endif', '']
    files[api+'_resources.h'] = '\n'.join(resources)
    files[api+'_bindings.h'] = '\n'.join(bindings)
    return files


def generate(path, output):
    from micros_tooling.config.artifacts import publish
    path = contract_path(path)
    files = artifacts(path, output)
    publish([(output, str(path), files)])
    return sorted(Path(output).resolve()/name for name in files)


def bindings(service):
    """Only this source file contains unit wiring and exposure policy."""
    _, contract, api, gpio, ports, commands = definition(service['_contract']['path'], service['_contract'].get('definition'))
    actual = {p['name']:p for p in service['_interface']['ports']}
    lines = [f'/* Generated from {api} unit bindings; edit the selected unit. */',
             f'#include "{api}_bindings.h"', f'#include "{api}_resources.h"']
    if commands:
        ports += [dict(name='rpc_request'),dict(name='rpc_response')]
        spec=service['_commands']
        lines += [f'uint32_t {api}_commands_contract(void) {{ return UINT32_C({spec["contract_id"]}); }}',
                  f'bool {api}_commands_exposed(uint32_t tag) {{', '    switch (tag) {']
        for tag, command in enumerate(commands, 10):
            if command in spec['exposed']: lines.append(f'    case {tag}: return true;')
        lines += ['    default: return false;', '    }', '}']
    for port in ports:
        key = actual.get(port['name'], {}).get('key', 0)
        lines.append(f'uint32_t {api}_{port["name"]}_binding(void) {{ return UINT32_C({key}); }}')
    actual_gpio = {g['name']:g for g in service['_interface']['gpio']}
    for resource in gpio:
        prefix=api+'_'+resource['name']; bound=actual_gpio[resource['name']]
        lines += [f'uint32_t {prefix}_binding(void) {{ return {bound["line"]}u; }}',
                  f'uint32_t {prefix}_pin(void) {{ return {bound["pin"]}u; }}',
                  f'micros_result_t {prefix}_open(const micros_service_args_t *a, micros_handle_t *h) {{',
                  f'    return a->api->gpio_open(a->context, {prefix}_binding(), h);', '}']
        kind = contract['hardware'][resource['name']].get('_type')
        if kind:
            operation = 'write' if kind == 'output' else 'read'
            call = 'gpio_read_analog' if kind == 'analog' else 'gpio_' + operation
            parameter = 'uint32_t value' if kind == 'output' else 'uint32_t *value'
            lines += [f'micros_result_t {prefix}_{operation}(const micros_service_args_t *a, micros_handle_t h, {parameter}) {{',
                      f'    if (!a || !a->api || !a->api->{call}) return MICROS_ERROR_UNSUPPORTED;',
                      f'    return a->api->{call}(a->context, h, value);', '}']
    return '\n'.join(lines)+'\n'
