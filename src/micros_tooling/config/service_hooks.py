"""Generate runtime plumbing while application C implements declared hooks."""
import json
from pathlib import Path
from micros_tooling.storage.packages import require


def command_parameters(api, command, spec, type_refs=None):
    from micros_tooling.config.type_generation import c_name
    type_refs = (type_refs or {}).get(command, {})
    params = [(f'{api}_context_t *', 'ctx')]
    for name, field in spec['args'].items():
        ctype = {'uint32': 'uint32_t', 'sint32': 'int32_t', 'bool': 'bool',
                 'enum': 'uint32_t', 'string': 'const char *'}[field['type']]
        if name in type_refs.get('args', {}) and field['type'] != 'string':
            ctype = c_name(api, type_refs['args'][name]) + '_t'
        params.append((ctype, 'arg_' + name))
    # Explicit return pointers also make added/removed outputs a signature change.
    for name, field in spec['returns'].items():
        ctype = {'uint32': 'uint32_t *', 'sint32': 'int32_t *', 'bool': 'bool *',
                 'enum': 'uint32_t *', 'string': 'char *'}[field['type']]
        if name in type_refs.get('returns', {}) and field['type'] != 'string':
            ctype = c_name(api, type_refs['returns'][name]) + '_t *'
        params.append((ctype, 'out_' + name))
        if field['type'] == 'string':
            params.append(('uint32_t', 'out_' + name + '_capacity'))
    return params


def hooks(api, ports, commands, type_refs=None):
    result = [(f'{api}_on_{event}', [(f'{api}_context_t *', 'ctx')], False)
              for event in ('start', 'step', 'stop')]
    for port in ports:
        if port['access'] == 'subscribe':
            result += [(f'{api}_on_{port["name"]}', [(f'{api}_context_t *', 'ctx'),
                         (f'const {api}_{port["name"]}_message_t *', 'message')], False),
                       (f'{api}_on_{port["name"]}_lost', [(f'{api}_context_t *', 'ctx')], False)]
    for command, spec in (commands or {}).items():
        result.append((f'{api}_handle_{command}', command_parameters(api, command, spec, type_refs), True))
    require(len({name for name, _, _ in result}) == len(result), 'Hook name collision; rename the subscription')
    return result


def signature(name, params):
    return f'micros_result_t {name}(' + ', '.join(f'{kind} {name}' for kind, name in params) + ')'


def hook_comment(api, name, ports, commands):
    """Brief, domain-independent descriptions of application hooks."""
    descriptions = {
        f'{api}_on_start': 'Initialize application state and start work after resources are ready.',
        f'{api}_on_step': 'Run periodic application work after event dispatch. The default runtime waits 1 ms between steps; timing is not guaranteed.',
        f'{api}_on_stop': 'Stop application work before generated resources are released.',
    }
    for port in ports:
        if port['access'] == 'subscribe':
            descriptions[f'{api}_on_{port["name"]}'] = 'Handle a received subscription message.'
            descriptions[f'{api}_on_{port["name"]}_lost'] = 'Handle lost subscription messages and resynchronize application state.'
    for command, spec in (commands or {}).items():
        from micros_tooling.commands.schema import describe
        details = [spec['description'] + '.']
        for direction in ('args', 'returns'):
            for field, definition in spec[direction].items():
                details.append(f'{"Input" if direction == "args" else "Output"} {field}: {describe(definition)}.')
        details.append('Populate all outputs before returning MICROS_OK; arguments are validated before dispatch.')
        descriptions[f'{api}_handle_{command}'] = ' '.join(details)
    import textwrap
    lines = textwrap.wrap('@brief ' + descriptions[name].replace('*/', '* /').replace('\n', ' '), width=92, break_on_hyphens=False)
    return '\n'.join(['/**', *[' * ' + line for line in lines], ' */'])


def starter(api, ports, commands, type_refs=None):
    lines = ['/* Application behavior. Generated plumbing never rewrites this file. */',
             f'#include "{api}_hooks.h"', '']
    for name, params, command in hooks(api, ports, commands, type_refs):
        lines += [hook_comment(api, name, ports, commands), signature(name, params), '{']
        lines += [f'    (void){name};' for _, name in params]
        lines += ['    /* TODO: implement application behavior. */',
                  '    return MICROS_ERROR_UNSUPPORTED;' if command else '    return MICROS_OK;', '}', '']
    return '\n'.join(lines)


def artifacts(path, contract, api, gpio, ports, commands):
    type_refs = contract['_type_refs']['commands']
    timers = contract['capabilities'].get('timers', 0)
    timer_names = list(contract.get('timers', {})) or [str(i) for i in range(timers)]
    require(type(timers) is int and 0 <= timers <= 64, 'Invalid timer count')
    state_header = path.parent / 'src' / (api + '_state.h')
    head = [f'/* Generated from {api} service hooks; do not edit. */',
            f'#ifndef {api.upper()}_HOOKS_H', f'#define {api.upper()}_HOOKS_H',
            '#include <stdbool.h>', '#include <micros/service.h>',
            f'#include {json.dumps(str(state_header))}',
            f'#include "{api}_resources.h"', f'#include "{api}_ipc.h"']
    if contract['types']:
        head.append(f'#include "{api}_types.h"')
    if contract['config_schema']:
        head.append(f'#include "{api}_config.h"')
    if commands:
        head.append(f'#include "{api}_commands.h"')
    head += ['typedef struct {', '    const micros_service_args_t *service;', f'    {api}_state_t state;']
    if contract['config_schema']:
        head.append(f'    {api}_config_t config;')
    resources = []
    for g in gpio:
        field = 'gpio_' + g['name']
        resources.append((field, f'{api}_{g["name"]}_open(args, &ctx->{field})',
                          f'args->api->gpio_close(args->context, ctx->{field})'))
    for p in ports:
        field = 'port_' + p['name']
        resources.append((field, f'{api}_{p["name"]}_open(args, &ctx->{field})',
                          f'{api}_{p["name"]}_close(args, ctx->{field})'))
    for field, _, _ in resources:
        head.append(f'    micros_handle_t {field};')
    for i in timer_names:
        head.append(f'    micros_handle_t timer_{i};')
    if commands:
        head.append(f'    {api}_commands_t commands;')
    head += ['    bool hook_started;', f'}} {api}_context_t;', '']
    for name, params, _ in hooks(api, ports, commands, type_refs):
        head += [hook_comment(api, name, ports, commands), signature(name, params) + ';']
    for timer in contract.get('timers', {}):
        head += [f'/** Open the declared {timer} timer. Generated stop owns cleanup; periods are in microseconds. */',
                 f'static inline micros_result_t {api}_timer_{timer}_open({api}_context_t *ctx, uint64_t delay_us, uint64_t period_us, micros_timer_callback_t callback, void *user_data) {{',
                 '    if (!ctx || !ctx->service || !callback) return MICROS_ERROR_INVALID_ARGUMENT;',
                 f'    if (ctx->timer_{timer}) return MICROS_ERROR_STATE;',
                 '    const micros_service_args_t *args = ctx->service;',
                 '    if (!args->api || !args->api->timer_open) return MICROS_ERROR_UNSUPPORTED;',
                 f'    return args->api->timer_open(args->context, delay_us, period_us, callback, user_data, &ctx->timer_{timer});', '}', '']
    head += ['#endif', '']
    code = [f'/* Generated from {api} lifecycle; do not edit. */', f'#include "{api}_hooks.h"',
            '#ifndef MICROS_SERVICE_TARGET', '#define MICROS_SERVICE_TARGET MICROS_BUILD_TARGET', '#endif', '']
    # Refresh service args on each entry: the host may supply a different args object.
    code += [f'static {api}_context_t *context(const micros_service_args_t *args) {{',
             f'    {api}_context_t *ctx = args->arena;', '    ctx->service = args;', '    return ctx;', '}',
             'static micros_result_t stop(const micros_service_args_t *args) {',
             f'    {api}_context_t *ctx = context(args);', '    micros_result_t first = MICROS_OK;',
             '    if (ctx->hook_started) {', '        ctx->hook_started = false;',
             f'        first = {api}_on_stop(ctx);', '    }']
    if commands:
        code += [f'    micros_result_t result = {api}_commands_close(args, &ctx->commands);',
                 '    if (!first) first = result;']
    closes = [(f'timer_{i}', f'args->api->timer_close(args->context, ctx->timer_{i})') for i in timer_names]
    closes += [(field, close) for field, _, close in reversed(resources)]
    for field, close in closes:
        code += [f'    if (ctx->{field}) {{', f'        micros_result_t result = {close};',
                 f'        if (!result) ctx->{field} = 0;', '        if (!first) first = result;', '    }']
    code += ['    return first;', '}', 'static micros_result_t initialize(const micros_service_args_t *args) {',
             f'    {api}_context_t *ctx = args->arena;', f'    *ctx = ({api}_context_t){{0}};',
             '    ctx->service = args;', '    micros_result_t result = MICROS_OK;']
    if contract['config_schema']:
        code.append(f'    result = {api}_config_decode(args->config_data, args->config_bytes, &ctx->config);')
    for _, opening, _ in resources:
        code.append(f'    if (!result) result = {opening};')
    if commands:
        code.append(f'    if (!result) result = {api}_commands_open(args, &ctx->commands);')
    code += ['    if (result) (void)stop(args);', '    return result;', '}',
             'static micros_result_t start(const micros_service_args_t *args) {',
             f'    {api}_context_t *ctx = context(args);', '    ctx->hook_started = true;',
             f'    micros_result_t result = {api}_on_start(ctx);',
             '    if (result) (void)stop(args);', '    return result;', '}',
             'static micros_result_t step(const micros_service_args_t *args) {',
             f'    {api}_context_t *ctx = context(args);', '    micros_result_t result;']
    if commands:
        code += [f'    result = {api}_commands_step(args, &ctx->commands);', '    if (result) return result;']
    for port in ports:
        if port['access'] != 'subscribe':
            continue
        name = port['name']
        code += ['    {', f'        {api}_{name}_message_t message;',
                 f'        result = {api}_{name}_read(args, ctx->port_{name}, &message);',
                 f'        if (!result) result = {api}_on_{name}(ctx, &message);',
                 f'        else if (result == MICROS_ERROR_MESSAGES_MISSED) result = {api}_on_{name}_lost(ctx);',
                 '        else if (result == MICROS_ERROR_EMPTY) result = MICROS_OK;',
                 '        if (result) return result;', '    }']
    code += [f'    result = {api}_on_step(ctx);', '    return result;', '}', '']
    for command, spec in (commands or {}).items():
        code += [f'micros_result_t {api}_{command}(const micros_service_args_t *args,',
                 f'    const {api}_{command}_request_t *request, {api}_{command}_response_t *response) {{',
                 '    (void)request; (void)response;']
        values = ['context(args)'] + ['request->' + name for name in spec['args']]
        for name, field in spec['returns'].items():
            values.append(('' if field['type'] == 'string' else '&') + 'response->' + name)
            if field['type'] == 'string':
                values.append(f'sizeof(response->{name})')
        code += [f'    return {api}_handle_{command}(' + ', '.join(values) + ');', '}']
    descriptor = contract['build'].get('descriptor', 'micros_descriptor')
    from micros_tooling.config.configuration import valid_identifier
    require(valid_identifier(descriptor), 'Invalid descriptor symbol')
    code += [f'const micros_service_descriptor_t {descriptor} = {{',
             '    .struct_bytes = sizeof(micros_service_descriptor_t),',
             '    .abi_major = MICROS_ABI_MAJOR, .abi_revision = MICROS_ABI_REVISION,',
             '    .target = MICROS_SERVICE_TARGET,',
             f'    .arena_bytes = sizeof({api}_context_t), .arena_alignment = _Alignof({api}_context_t),',
             '    .stack_bytes = 4096,', '    .init = initialize, .start = start, .step = step, .stop = stop,', '};',
             f'const micros_service_descriptor_t *micros_service_query(void) {{ return &{descriptor}; }}', '']
    return {api+'_hooks.h': '\n'.join(head), api+'_lifecycle.c': '\n'.join(code)}
