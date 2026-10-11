"""Generate native command handlers and bounded lifecycle helpers; never edit user code."""
from .schema import message_name
import hashlib
from micros_tooling.storage.packages import canonical_json


def handler_schema(definition):
    """Semantic handler contract, independent of descriptions and board exposure."""
    return hashlib.sha256(canonical_json({key: definition[key] for key in ("args", "returns")})).hexdigest()[:16]


def handler_guard(api, command, definition):
    macro = f"{api}_{command}_HANDLER_SCHEMA".upper()
    return (f'_Static_assert({macro} == UINT64_C(0x{handler_schema(definition)}), '
            f'"{api}_{command}: command schema changed; review handler and update expected schema");')



def artifacts(spec):
    api=spec['api']; commands=spec['commands']; independent=spec.get('independent', False)
    exposed=list(commands) if independent else spec['exposed']
    contract=f'{api}_commands_contract()' if independent else f'{contract}'
    req=f'micros_commands_{api}_Request'; res=f'micros_commands_{api}_Response'
    header=[f'/* Generated from {api} command declarations; do not edit. */',f'#ifndef {api.upper()}_COMMANDS_H',f'#define {api.upper()}_COMMANDS_H',
            '/* Handlers run on the service task: keep work bounded; fill response and return MICROS_OK or an error. */',
            '#include <micros/service.h>', f'#include "{api}_rpc_request.pb.h"', f'#include "{api}_rpc_response.pb.h"']
    if spec.get('type_refs'):
        header.append(f'#include "{api}_types.h"')
    for command, definition in commands.items():
        header.append(f'#define {api.upper()}_{command.upper()}_HANDLER_SCHEMA UINT64_C(0x{handler_schema(definition)})')
        for direction, source in [('request',req),('response',res)]:
            header.append(f'typedef {source}_{message_name(command)} {api}_{command}_{direction}_t;')
        for direction in ('args','returns'):
            for field,value in definition[direction].items():
                if value['type']=='enum':
                    for i,choice in enumerate(value['choices']):
                        macro=f'{api}_{command}_{direction}_{field}_{choice}'.upper()
                        reference = spec.get('type_refs', {}).get(command, {}).get(direction, {}).get(field)
                        if reference:
                            from micros_tooling.config.type_generation import c_name
                            constant = c_name(api, reference).upper() + '_' + choice.upper()
                        else: constant = f'UINT32_C({i})'
                        header.append(f'#define {macro} {constant}')
        header += [f'/* {definition["description"].replace("*/", "* /").replace(chr(10), " ")} */',
                   f'micros_result_t {api}_{command}(const micros_service_args_t *, const {api}_{command}_request_t *, {api}_{command}_response_t *);']
    header += [f'typedef struct {{ micros_handle_t request, response; {res} last; }} {api}_commands_t;',
               f'micros_result_t {api}_commands_open(const micros_service_args_t *, {api}_commands_t *);',
               f'micros_result_t {api}_commands_step(const micros_service_args_t *, {api}_commands_t *);',
               f'micros_result_t {api}_commands_close(const micros_service_args_t *, {api}_commands_t *);', '#endif','']
    code=[f'/* Generated from {api} command declarations; do not edit. */',f'#include "{api}_commands.h"']
    if independent: code.append(f'#include "{api}_bindings.h"')
    if not exposed:
        for operation in ('open','step','close'):
            code.append(f'micros_result_t {api}_commands_{operation}(const micros_service_args_t *a, {api}_commands_t *s) {{ (void)a; (void)s; return MICROS_OK; }}')
        return '\n'.join(header),'\n'.join(code)+'\n'
    code += [f'#include "{api}_ipc.h"',
             f'micros_result_t {api}_commands_close(const micros_service_args_t *a, {api}_commands_t *s) {{',
             '    micros_result_t first=MICROS_OK, r;',
             f'    if (s->request) {{ r={api}_rpc_request_close(a,s->request); if (!r) s->request=0; if (!first) first=r; }}',
             f'    if (s->response) {{ r={api}_rpc_response_close(a,s->response); if (!r) s->response=0; if (!first) first=r; }}',
             '    return first;', '}',
             f'micros_result_t {api}_commands_open(const micros_service_args_t *a, {api}_commands_t *s) {{',
             *([f'    if (!{api}_rpc_request_binding()) return MICROS_OK;'] if independent else []),
             f'    micros_result_t r={api}_rpc_request_open(a,&s->request);',
             f'    if (!r) r={api}_rpc_response_open(a,&s->response);',
             f'    if (r) {{ (void){api}_commands_close(a,s); return r; }}',
             '    /* Discard retained requests on startup/restart; never replay a former instance\'s work. */',
             f'    {req} ignored;',
             f'    for (unsigned i=0; i<10; ++i) {{',
             f'        r={api}_rpc_request_read(a,s->request,&ignored);',
             '        if (r==MICROS_ERROR_EMPTY) break;',
             f'        if (r && r!=MICROS_ERROR_MESSAGES_MISSED && r!=MICROS_ERROR_INVALID_ARGUMENT) {{ (void){api}_commands_close(a,s); return r; }}',
             '    }',
             f'    s->last=({res}){{0}};',
             '    return MICROS_OK;', '}',
             f'micros_result_t {api}_commands_step(const micros_service_args_t *a, {api}_commands_t *s) {{',
             *(['    if (!s->request) return MICROS_OK;'] if independent else []),
             f'    {req} request;', f'    micros_result_t r={api}_rpc_request_read(a,s->request,&request);',
             '    if (r==MICROS_ERROR_EMPTY || r==MICROS_ERROR_MESSAGES_MISSED || r==MICROS_ERROR_INVALID_ARGUMENT) return MICROS_OK;',
             '    if (r) return r;',
             '    if (!request.request_id) return MICROS_OK;',
             '    /* Re-publish the most recent reply on duplicate delivery, without rerunning its handler. */',
             '    if (request.request_id == s->last.request_id)',
             f'        return {api}_rpc_response_publish(a,s->response,&s->last);',
             f'    s->last=({res}){{.request_id=request.request_id, .contract_id={contract}, .result=MICROS_ERROR_UNSUPPORTED}};',
             f'    if (request.contract_id=={contract}) switch (request.which_command) {{']
    def checks(fields, base):
        expressions=[]
        for field,specification in fields.items():
            expr=base+'.'+field;kind=specification['type']
            if kind=='enum':expressions.append(f'{expr} < {len(specification["choices"])}u')
            elif kind in ('uint32','sint32'):
                if specification['min'] != (0 if kind=='uint32' else -2**31): expressions.append(f'{expr} >= {specification["min"]}'+('u' if kind=='uint32' else ''))
                if specification['max'] != (2**32-1 if kind=='uint32' else 2**31-1): expressions.append(f'{expr} <= {specification["max"]}'+('u' if kind=='uint32' else ''))
            elif kind=='string':
                # Bounded scan includes the terminator. No libc dependency or unbounded strlen.
                expressions.append('('+' || '.join(f'{expr}[{i}] == 0' for i in range(specification['max_bytes']+1))+')')
        return ' && '.join(expressions) or '1'
    for tag,(command,definition) in enumerate(commands.items(),10):
        if command not in exposed:continue
        code += [f'    case {tag}:',
                 *([f'        if (!{api}_commands_exposed({tag}u)) break;'] if independent else []),
                 f'        s->last.which_command={tag};',
                 f'        if (!({checks(definition["args"], "request.command."+command)})) {{ s->last.result=MICROS_ERROR_INVALID_ARGUMENT; break; }}',
                 f'        s->last.result={api}_{command}(a,&request.command.{command},&s->last.command.{command});',
                 f'        if (!s->last.result && !({checks(definition["returns"], "s->last.command."+command)})) s->last.result=MICROS_ERROR_SERVICE;',
                 '        break;']
    code += ['    default: break;', '    }',
             '    /* On error omit handler output, which may contain invalid or incomplete fields. */',
             '    if (s->last.result) s->last.which_command=0;',
             f'    return {api}_rpc_response_publish(a,s->response,&s->last);', '}', '']
    return '\n'.join(header),'\n'.join(code)


def scaffold_source(contract):
    from micros_tooling.config.configuration import read_toml
    from .schema import normalize
    service=read_toml(contract)['service'];api=service['build']['api']
    from micros_tooling.config.configuration import valid_identifier
    from micros_tooling.storage.packages import require
    require(valid_identifier(api), 'Invalid command API name')
    require(service['build'].get('lifecycle') != 'hooks',
            'Hook services use scaffold-service --preview; command transport is generated automatically')
    commands=normalize(service['commands'],service.get('types'))
    lines=[f'/* Command handlers for {service["name"]}. This file is user-owned. */',f'#include "{api}_commands.h"','']
    for command in commands:
        lines += [handler_guard(api, command, commands[command]),
                  f'micros_result_t {api}_{command}(const micros_service_args_t *service,',
                  f'    const {api}_{command}_request_t *request, {api}_{command}_response_t *response)',
                  '{', '    (void)service; (void)request; (void)response;',
                  '    /* Implement the command and populate response on success. */',
                  '    return MICROS_ERROR_UNSUPPORTED;', '}', '']
    return '\n'.join(lines)


def scaffold(contract, destination):
    from pathlib import Path
    content = scaffold_source(contract)
    path=Path(destination)
    # Exclusive creation is intentional: neither scaffold nor generation overwrites handlers.
    with path.open('x') as output:output.write(content)
    return path
