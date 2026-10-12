"""One-time, user-owned service starters derived from an existing contract."""
from pathlib import Path
import re
import tempfile

from micros_tooling.config.service_generation import definition
from micros_tooling.storage.packages import require


def new(path, example=None):
    """Create a native service declaration and hook sources in a new directory."""
    from micros_tooling.config.composition import toml
    destination = Path(path).absolute()
    require(re.fullmatch('[a-z][a-z0-9_-]{0,47}', destination.name),
            'Use a service directory name starting with a lowercase letter, followed by lowercase letters, digits, hyphens or underscores.')
    require(not destination.exists() and not destination.is_symlink(),
            f'Destination already exists: {destination}. To scaffold its existing service.toml, omit --new.')
    api = destination.name.replace('-', '_')
    declaration = dict(service=dict(name='app.' + destination.name, version='0.1.0',
        build=dict(api=api, lifecycle='hooks', sources=['src/service.c'], descriptor='micros_descriptor'),
        config_schema={}))
    require(example in (None, 'counter'), 'Unknown starter service example')
    if example == 'counter':
        declaration['service']['types'] = dict(Count=dict(type='uint32'))
        declaration['service']['commands'] = {
            name: dict(returns=dict(count='Count')) for name in ('read', 'increment', 'reset')}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.micros-service-', dir=destination.parent) as temporary:
        staging = Path(temporary) / destination.name
        staging.mkdir()
        (staging / 'service.toml').write_text(toml(declaration,
            comment='Service-owned behavior and settings. Select this service in units/host.toml or a unit file.'))
        created = create(staging)
        if example == 'counter':
            from micros_tooling.config.repository import ROOT
            template = ROOT / 'tools/templates/service-counter'
            for filename, output in (('service.c', 'service.c'), ('state.h', api + '_state.h')):
                (staging / 'src' / output).write_text((template / filename).read_text().replace('COUNTER', api.upper()).replace('counter', api))
        relative = [Path('service.toml'), *(file.relative_to(staging.resolve()) for file in created)]
        staging.rename(destination)
    return [destination / file for file in relative]


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
