#!/usr/bin/env python3
"""Build three independently linked Feather V2 service packages using the pinned SDK."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from tools.packaging.demo_packages import manifest
from micros_tooling.config.configuration import generate_service_headers
from micros_tooling.storage.packages import build_package, canonical_json, require
from micros_tooling.config.resources import load_board, verify_board_firmware, validate_bindings

ROOT = Path(__file__).resolve().parents[2]


def fixture_board(board):
    definition = load_board(board)
    require(definition is not None, 'Select a release fixture board')
    lines = {item['name']: item for item in definition['gpio']}
    require('user_button' in lines and lines['user_button']['direction'] == 'input'
            and 'red_led' in lines and lines['red_led']['direction'] == 'output',
            'Release fixture requires user_button input and red_led output')
    bindings = {key: definition[key] for key in ('gpio', 'recovery_button')}
    validate_bindings(bindings)
    return definition, lines, bindings


def build(firmware, output, board):
    definition, lines, bindings = fixture_board(board)
    verify_board_firmware(definition, firmware)
    generate_service_headers(ROOT / "tests/fixtures/configuration/micros.toml",
                             ROOT / "tests/fixtures/configuration/board.toml")
    output.mkdir(parents=True, exist_ok=True)
    schema = (ROOT / 'src/sdk/protos/button/v1/button_state.proto').read_bytes()
    selection = {}
    for slot, (name, role) in enumerate((('button', 0), ('logger', 1), ('led', 3))):
        directory = output / name
        subprocess.run([sys.executable, str(ROOT / 'src/micros_tooling/platforms/esp32/build_service.py'),
            '--firmware', str(firmware), '--output', str(directory), '--slot', str(slot),
            '--source', str(ROOT / 'tests/fixtures/sensor-pipeline/src/service.c'),
            '--protobuf-directory', str(ROOT / 'examples/services/button/generated'), '--descriptor-symbol', 'descriptor',
            '--define', f'PIPELINE_ROLE={role}', '--define', 'PIPELINE_HARDWARE=1',
            '--define', f'DEMO_BUTTON_LINE={lines["user_button"]["line"]}',
            '--define', f'DEMO_LED_LINE={lines["red_led"]["line"]}'], check=True)
        image = (directory / 'service.mimg').read_bytes()
        description = manifest('board.' + name, 'publish' if role == 0 else 'subscribe', image, schema)
        description['target'] = 2
        description['board_bindings'] = bindings
        description['memory'] = json.loads((directory / 'report.json').read_text())['memory']
        if role in (0, 3):
            description['capabilities']['gpio'] = [lines['user_button' if role == 0 else 'red_led']['line']]
            description['capabilities']['handles'] += 1
        (output / f'{name}.msp').write_bytes(build_package(description, image, {'sample': schema}))
        selection['board.' + name] = str(output / f'{name}.msp')
    (output / 'packages.json').write_bytes(canonical_json(selection))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware', type=Path, default=Path('build/esp32-runtime/micros_runtime.elf'))
    parser.add_argument('--output', type=Path, default=Path('build/device-demo'))
    parser.add_argument('--board', type=Path, default=ROOT / 'tests/fixtures/release-board.toml')
    args = parser.parse_args()
    build(args.firmware, args.output, args.board)
