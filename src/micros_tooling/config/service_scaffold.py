"""One-time, user-owned service starters derived from an existing contract."""
from pathlib import Path

from micros_tooling.config.service_generation import definition
from micros_tooling.storage.packages import require


def artifacts(path):
    path, contract, api, gpio, ports, commands = definition(path)
    require(contract['build'].get('lifecycle') == 'hooks',
            'Set [service.build] lifecycle = "hooks" to scaffold application hooks')
    require('src/service.c' in contract['build'].get('sources', []),
            'Hook scaffolding requires src/service.c in build.sources')
    from micros_tooling.config.service_hooks import starter
    header = f'''/* Application-owned state; add your fields here. */
#ifndef {api.upper()}_STATE_H
#define {api.upper()}_STATE_H
#include <stdint.h>
typedef struct {{
    uint8_t reserved; /* Replace with your application state. */
}} {api}_state_t;
#endif
'''
    return path.parent, {Path('src/service.c'): starter(api, ports, commands, contract['_type_refs']['commands']),
                         Path('src')/(api+'_state.h'): header}


def create(path):
    root, files = artifacts(path)
    # Preflight the whole plan before creating any file or directory.
    for relative in files:
        destination = root / relative
        require(not destination.exists() and not destination.is_symlink(),
                f'Refusing to overwrite existing file: {destination}')
        require(not any(parent.is_symlink() for parent in destination.parents if parent != root and root in parent.parents),
                f'Refusing scaffold path through a symlink: {destination}')
        require(all(not parent.exists() or parent.is_dir() for parent in destination.parents),
                f'Scaffold parent is not a directory: {destination}')
    created = []
    try:
        for relative, content in files.items():
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('x') as output:
                created.append(destination)
                output.write(content)
    except Exception:
        for destination in reversed(created):
            destination.unlink()
        raise
    return created
