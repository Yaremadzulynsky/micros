#!/usr/bin/env python3
"""Build deterministic M4 packages for the independently linked sensor pipeline."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from micros_tooling.storage.native_image import NATIVE_HOST_TARGET
from micros_tooling.storage.packages import ABI_MAJOR, ABI_REVISION, build_package, canonical_json, canonical_schema, digest


def manifest(name, role, image, schema, version='1.0.0'):
    # The current pipeline state is three 64-bit fields plus uint32 and native
    # padding: sizeof=32, align=8. Native admission verifies this independently.
    return {'format': 1, 'name': name, 'version': version, 'target': NATIVE_HOST_TARGET,
            'abi': {'major': ABI_MAJOR, 'revision': ABI_REVISION}, 'image_sha256': digest(image),
            'memory': {'arena_bytes': 32, 'arena_alignment': 8, 'stack_bytes': 4096},
            'capabilities': {'handles': 2 if role == 'publish' else 1, 'timers': 1 if role == 'publish' else 0, 'gpio': []},
            'channels': [{'name': 'button.state', 'key': 1, 'access': role, 'policy': 'stream', 'depth': 8,
                          'max_payload': 64, 'schema': 'sample', 'interface': 'micros.button.state',
                          'major': 1, 'minor': 1, 'accepts_minor': [1, 1]}],
            'schemas': {'sample': digest(canonical_schema(schema))}, 'persistent_data_version': 0}


def build_demo(build, output):
    output.mkdir(parents=True, exist_ok=True)
    schema = (Path(__file__).resolve().parents[2] / 'src/sdk/protos/button/v1/button_state.proto').read_bytes()
    selection = {}
    for participant in ('publisher', 'fast', 'slow'):
        image = (build / f'pipeline_{participant}.mimg').read_bytes()
        service_name = f'demo.{participant}'
        description = manifest(service_name, 'publish' if participant == 'publisher' else 'subscribe', image, schema)
        (output / f'{participant}.msp').write_bytes(build_package(description, image, {'sample': schema}))
        (output / f'{participant}.manifest.json').write_bytes(canonical_json(description))
        selection[service_name] = '1.0.0'
    (output / 'enabled.json').write_bytes(canonical_json(selection))
    return selection


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, default=Path('build/host'))
    parser.add_argument('--output', type=Path, default=Path('build/demo-packages'))
    args = parser.parse_args()
    build_demo(args.build, args.output)
