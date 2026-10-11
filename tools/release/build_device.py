#!/usr/bin/env python3
"""Build the V1 base and independently linked hardware demo/fault images; never flash."""

import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tools.packaging.device_demo import fixture_board
from micros_tooling.config.resources import board_partitions
from micros_tooling.storage.store import atomic_write
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--network",
    action="store_true",
    help="Use locally provisioned Wi-Fi/TLS credentials",
)
parser.add_argument('--board', type=Path, default=ROOT / 'tests/fixtures/release-board.toml')
parser.add_argument('--relay-credentials', type=Path)
args = parser.parse_args()
definition, lines, bindings = fixture_board(args.board)
build = ROOT / "build/esp32-runtime"
firmware = build / "micros_runtime.elf"


def run(*arguments):
    subprocess.run(list(map(str, arguments)), cwd=ROOT, check=True)


if args.network:
    arguments = [sys.executable, ROOT / "src/micros_tooling/platforms/esp32/build_network.py",
                 '--board', args.board, '--project', ROOT / 'tests/fixtures/configuration/micros.toml']
    if args.relay_credentials:
        arguments += ['--relay-credentials', args.relay_credentials]
    run(*arguments)
else:
    partition = build / 'partitions.csv'
    configuration = build / 'sdkconfig'
    atomic_write(partition, board_partitions(definition).encode())
    # Explicit board selection must also override a previous SDK flash layout.
    retained = [line for line in (configuration.read_text().splitlines() if configuration.exists() else [])
                if 'CONFIG_ESPTOOLPY_FLASHSIZE' not in line
                and 'CONFIG_PARTITION_TABLE_CUSTOM_FILENAME' not in line
                and 'CONFIG_PARTITION_TABLE_FILENAME' not in line]
    flash_mb = definition.get('flash_mb', 8)
    retained += [f'CONFIG_ESPTOOLPY_FLASHSIZE_{flash_mb}MB=y',
                 f'CONFIG_ESPTOOLPY_FLASHSIZE="{flash_mb}MB"',
                 f'CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="{partition}"']
    atomic_write(configuration, ('\n'.join(retained) + '\n').encode())
    run(
        "idf.py",
        "-C",
        ROOT / "src/firmware/platforms/esp32/sdk",
        "-B",
        build,
        "-D",
        "SDKCONFIG=" + str(build / "sdkconfig"),
        '-D', 'MICROS_BOARD_FILE=' + str(args.board.resolve()),
        '-D', 'SDKCONFIG_DEFAULTS=' + str(ROOT / 'src/firmware/platforms/esp32/sdk/sdkconfig.defaults'),
        "build",
    )
run(sys.executable, ROOT / "tools/packaging/device_demo.py", "--board", args.board)
common = [
    sys.executable,
    ROOT / "src/micros_tooling/platforms/esp32/build_service.py",
    "--firmware",
    firmware,
]
run(
    *common,
    "--output",
    ROOT / "build/device-cpp",
    "--slot",
    3,
    "--source",
    ROOT / "tests/fixtures/cpp-lifecycle/service.cpp"
)
run(
    *common,
    "--output",
    ROOT / "build/device-failure",
    "--slot",
    0,
    "--source",
    ROOT / "tests/hardware/failure.c",
    "--descriptor-symbol",
    "descriptor"
)
run(
    *common,
    "--output",
    ROOT / "build/device-led-update",
    "--slot",
    2,
    "--source",
    ROOT / "tests/fixtures/sensor-pipeline/src/service.c",
    "--protobuf-directory",
    ROOT / "examples/services/button/generated",
    "--descriptor-symbol",
    "descriptor",
    "--define",
    "PIPELINE_ROLE=3",
    "--define",
    "PIPELINE_HARDWARE=1",
    "--define",
    "LED_HALF_PERIOD_SAMPLES=2",
    "--define", f"DEMO_BUTTON_LINE={lines['user_button']['line']}",
    "--define", f"DEMO_LED_LINE={lines['red_led']['line']}"
)
