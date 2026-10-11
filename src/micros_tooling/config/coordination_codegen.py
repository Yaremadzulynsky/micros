"""Generate a bounded, per-instance callback adapter over typed coordination ports."""


def callback_artifacts(name, ports):
    from micros_tooling.storage.packages import require

    ports = [port for port in ports if port.get('kind')]
    if not ports:
        return [], []
    require(all(port['name'] != 'coordination' for port in ports),
            'coordination is reserved for the generated service adapter')
    args = 'const micros_service_args_t *args'
    header = ['#include <micros/coordination_service.h>']
    callbacks, fields, declarations, source = [], ['    unsigned initialized;'], [], []
    open_lines, close_lines, dispatch = [], [], []

    def function(signature, lines):
        declarations.append('static inline ' + signature + ';')
        source.extend(['static inline ' + signature, '{', *['    ' + line for line in lines], '}'])

    for port in ports:
        port_name, kind, access = port['name'], port['kind'], port['access']
        prefix = f'{name}_{port_name}'
        message = f'{prefix}_message_t'
        handle = f'context->{port_name}_port'
        fields.append(f'    micros_handle_t {port_name}_port;')
        open_lines += [f'status = {prefix}_open(args, &{handle});',
                       f'if (status) {{ {name}_coordination_close(args); return status; }}']
        close_lines += [f'if ({handle}) {{', f'    micros_result_t status = {prefix}_close(args, {handle});',
                        '    if (!first_error) first_error = status;', f'    {handle} = 0;', '}']
        preamble = [f'{name}_coordination_t *context = {name}_coordination_context(args);',
                    'if (!context->initialized) return MICROS_ERROR_STATE;']

        if access == 'publish' and kind in ('state', 'event'):
            operation = 'set' if kind == 'state' else 'emit'
            function(f'micros_result_t {name}_{operation}_{port_name}({args}, const {message} *message)',
                     preamble + ['micros_coord_info_t info = {0};',
                                 f'return {prefix}_{operation}(args, {handle}, message, &info);'])
        elif access == 'publish':
            fields += [f'    unsigned {port_name}_pending;', f'    micros_coord_info_t {port_name}_ticket;']
            close_lines.append(f'context->{port_name}_pending = 0;')
            result_type = f'{prefix}_result_t'
            header += [f'typedef struct {{ uint32_t status; {message} message; }} {result_type};']
            callback = f'on_{port_name}_finished'
            callbacks.append(f'    micros_result_t (*{callback})({args}, const {result_type} *result);')
            function(f'micros_result_t {name}_request_{port_name}({args}, const {message} *request)',
                     preamble + [f'if (context->{port_name}_pending) return MICROS_ERROR_STATE;',
                                 f'micros_result_t status = {prefix}_request(args, {handle}, request, &context->{port_name}_ticket);',
                                 f'if (!status) context->{port_name}_pending = 1;', 'return status;'])
            dispatch += [f'if (context->{port_name}_pending) {{',
                         f'    {result_type} result = {{0}};', '    micros_coord_info_t info = {0};',
                         f'    status = {prefix}_result(args, {handle}, &result.message, &info);',
                         '    if (status && status != MICROS_ERROR_EMPTY) return status;',
                         '    if (!status) {',
                         f'        if (info.generation != context->{port_name}_ticket.generation ||',
                         f'            info.revision != context->{port_name}_ticket.revision) return MICROS_ERROR_STATE;',
                         '        if (info.status != MICROS_COORD_ACCEPTED) {',
                         '            if (info.status < MICROS_COORD_COMPLETED || info.status > MICROS_COORD_INDETERMINATE) return MICROS_ERROR_STATE;',
                         '            result.status = info.status;',
                         f'            context->{port_name}_pending = 0;',
                         f'            status = callbacks->{callback}(args, &result);',
                         '            if (status) return status;', '        }', '    }', '}']
        elif kind == 'action':
            callback = f'on_{port_name}_requested'
            callbacks.append(f'    micros_result_t (*{callback})({args}, const {message} *request, micros_action_t action);')
            function(f'micros_result_t {name}_complete_{port_name}({args}, micros_action_t action, uint32_t status, const {message} *result)',
                     preamble + [f'if (action._port != {handle}) return MICROS_ERROR_STALE_HANDLE;',
                                 'action._identity.status = status;',
                                 f'return {prefix}_complete(args, {handle}, result, &action._identity);'])
            dispatch += ['{', f'    {message} request = {{0}};',
                         '    micros_action_t action = {0};', f'    action._port = {handle};',
                         f'    status = {prefix}_next(args, {handle}, &request, &action._identity);',
                         '    if (status && status != MICROS_ERROR_EMPTY) return status;',
                         '    if (!status) {',
                         f'        status = callbacks->{callback}(args, &request, action);',
                         '        if (status) return status;', '    }', '}']
        else:
            callback = f'on_{port_name}_' + ('changed' if kind == 'state' else 'event')
            callbacks.append(f'    micros_result_t (*{callback})({args}, const {message} *message, const micros_coord_info_t *info);')
            dispatch += ['{', f'    {message} message = {{0}};', '    micros_coord_info_t info = {0};',
                         f'    status = {prefix}_read(args, {handle}, &message, &info);',
                         '    if (status && status != MICROS_ERROR_EMPTY) return status;',
                         '    if (!status) {',
                         f'        status = callbacks->{callback}(args, &message, &info);',
                         '        if (status) return status;', '    }', '}']

    header += ['/* Adapter-owned state. Use the service macro; do not edit these fields. */',
               'typedef struct {', *fields, f'}} {name}_coordination_t;',
               'typedef struct {', *(callbacks or ['    unsigned reserved;']), f'}} {name}_callbacks_t;']
    declarations.append(f'{name}_coordination_t *{name}_coordination_context({args});')
    callback_names = [line.split('(*')[1].split(')')[0] for line in callbacks]
    checks = ['if (!callbacks) return MICROS_ERROR_INVALID_ARGUMENT;']
    checks += [f'if (!callbacks->{callback}) return MICROS_ERROR_INVALID_ARGUMENT;' for callback in callback_names]
    function(f'micros_result_t {name}_coordination_open({args}, const {name}_callbacks_t *callbacks)',
             [f'{name}_coordination_t *context = {name}_coordination_context(args);',
              'if (context->initialized) return MICROS_ERROR_STATE;', *checks,
              'micros_result_t status;', *open_lines, 'context->initialized = 1;', 'return MICROS_OK;'])
    function(f'micros_result_t {name}_coordination_close({args})',
             [f'{name}_coordination_t *context = {name}_coordination_context(args);',
              'micros_result_t first_error = MICROS_OK;', *close_lines,
              'context->initialized = 0;', 'return first_error;'])
    function(f'micros_result_t {name}_coordination_dispatch({args}, const {name}_callbacks_t *callbacks)',
             [f'{name}_coordination_t *context = {name}_coordination_context(args);',
              'if (!context->initialized) return MICROS_ERROR_STATE;', *checks,
              *(['micros_result_t status;'] if dispatch else []), *dispatch, 'return MICROS_OK;'])
    header += declarations + source
    header += [f'#define {name.upper()}_SERVICE(state_type, stack_size, hooks, callbacks) \\',
               f'    MICROS_COORDINATION_SERVICE({name}, state_type, stack_size, hooks, callbacks)']
    return header, []
