"""C names and helpers from the one shared service type declaration."""
import re


def c_name(api, name):
    return api + '_' + re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()


def artifacts(api, types):
    lines = [f'/* Generated from {api} named types; edit service.toml. */',
             f'#ifndef {api.upper()}_TYPES_H', f'#define {api.upper()}_TYPES_H',
             '#include <stdint.h>', '#include <stdbool.h>', '#include <stddef.h>']
    for name, spec in types.items():
        prefix = c_name(api, name)
        kind = spec['type']
        ctype = {'uint32': 'uint32_t', 'sint32': 'int32_t', 'enum': 'uint32_t', 'bool': 'bool', 'string': 'char'}[kind]
        if kind == 'string':
            lines.append(f'typedef char {prefix}_t[{spec["max_bytes"]+1}];')
            lines.append(f'#define {prefix.upper()}_MAX_BYTES {spec["max_bytes"]}u')
            continue
        lines.append(f'typedef {ctype} {prefix}_t;')
        if kind == 'enum':
            for index, choice in enumerate(spec['choices']):
                lines.append(f'#define {prefix.upper()}_{choice.upper()} UINT32_C({index})')
            lines += [f'#define {prefix.upper()}_COUNT UINT32_C({len(spec["choices"])})',
                      f'static inline bool {prefix}_valid({prefix}_t value) {{ return value < {prefix.upper()}_COUNT; }}',
                      f'static inline const char *{prefix}_name({prefix}_t value) {{', '    switch (value) {']
            for choice in spec['choices']:
                lines.append(f'    case {prefix.upper()}_{choice.upper()}: return "{choice}";')
            lines += ['    default: return NULL;', '    }', '}']
        elif kind in ('uint32', 'sint32'):
            low, high = (0, 2**32-1) if kind == 'uint32' else (-2**31, 2**31-1)
            checks = []
            if spec.get('min', low) > low: checks.append(f'value >= {spec["min"]}')
            if spec.get('max', high) < high: checks.append(f'value <= {spec["max"]}')
            expression = ' && '.join(checks) or 'true'
            lines.append(f'static inline bool {prefix}_valid({prefix}_t value) {{ (void)value; return {expression}; }}')
    return '\n'.join(lines + ['#endif', ''])


def configuration(header, api, references):
    if not references: return header
    header = header.replace('#include <micros/service.h>', f'#include <micros/service.h>\n#include "{api}_types.h"')
    for field, name in references.items():
        prefix = c_name(api, name)
        header = header.replace(f'uint32_t {field};', f'{prefix}_t {field};')
        pattern = r'#define (' + re.escape(api.upper() + '_' + field.upper() + '_') + r')([A-Z0-9_]+) UINT32_C\(\d+\)\n'
        def alias(match):
            original = match[1] + match[2]
            target = prefix.upper() + '_' + match[2]
            return '' if original == target else f'#define {original} {target}\n'
        header = re.sub(pattern, alias, header)
    return header
