#!/usr/bin/env python3
"""Configure/build the network-enabled MCU profile using local private provisioning files."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
from micros_tooling.deployment.provision import provision
from micros_tooling.config.resources import select_board, load_board, board_partitions
from micros_tooling.storage.store import atomic_write
from micros_tooling.storage.packages import require

ROOT = Path(__file__).resolve().parents[4]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--credentials", type=Path, default=ROOT / "build/private")
parser.add_argument("--build", type=Path, default=ROOT / "build/esp32-runtime")
parser.add_argument("--project", type=Path, required=True)
parser.add_argument("--board", type=Path)
parser.add_argument("--relay-credentials", type=Path)
parser.add_argument("--ota", action="store_true", help="build the slim A/B base (initial installation requires USB)")
args = parser.parse_args()
credentials = args.credentials.resolve()
build = args.build.resolve()
board = select_board(args.project, args.board)
require(board is not None, "Select a board definition with --board PATH")
definition = load_board(board)
flash_mb = definition.get("flash_mb", 8)
partition_file = build / "generated/partitions.csv"
ota = args.ota or (build / "sdkconfig").exists() and "CONFIG_MICROS_BASE_OTA=y" in (build / "sdkconfig").read_text()
atomic_write(partition_file, board_partitions(definition, ota=ota).encode())
provision(credentials)
from micros_tooling.config.configuration import read_toml
from micros_tooling.communication.relay_config import enrolled_server_settings
relay_url = enrolled_server_settings(read_toml(args.project), args.relay_credentials)
relay_settings = ""
if relay_url:
    require(args.relay_credentials is not None, "Management server enabled; pass --relay-credentials from micros server enroll")
    relay_token = (args.relay_credentials / "relay.token").read_text().strip()
    require(len(relay_token) == 64 and all(c in "0123456789abcdef" for c in relay_token), "Invalid relay enrollment token")
    require((args.relay_credentials / "relay-ca.pem").is_file(), "Relay CA file missing")
    relay_settings = ("CONFIG_MICROS_RELAY_ENABLED=y\nCONFIG_MICROS_RELAY_URL=" + json.dumps(relay_url)
                      + "\nCONFIG_MICROS_RELAY_TOKEN=" + json.dumps(relay_token) + "\n")
defaults = [
    ROOT / "src/firmware/platforms/esp32/sdk/sdkconfig.defaults",
    credentials / "sdkconfig.management",
]
# Merge only the explicitly provisioned settings into an existing local SDK
# configuration. New defaults alone would not override saved menuconfig values.
configuration = build / "sdkconfig"
# Only credentials/transport enrollment are replaced. Preserve service-memory
# and other base feature settings explicitly selected for this build.
provisioned_keys = ("CONFIG_MICROS_REMOTE_ENABLED", "CONFIG_MICROS_MANAGEMENT_TOKEN",
                    "CONFIG_MICROS_RELAY_ENABLED", "CONFIG_MICROS_RELAY_URL",
                    "CONFIG_MICROS_RELAY_TOKEN")
retained = [
    line
    for line in (configuration.read_text().splitlines() if configuration.exists() else [])
    if not any(line.startswith(key + "=") or line == f"# {key} is not set"
               for key in provisioned_keys)
    and "CONFIG_ESPTOOLPY_FLASHSIZE" not in line
    and "CONFIG_PARTITION_TABLE_CUSTOM_FILENAME" not in line
    and "CONFIG_PARTITION_TABLE_FILENAME" not in line
]
retained += [f"CONFIG_ESPTOOLPY_FLASHSIZE_{flash_mb}MB=y",
             f'CONFIG_ESPTOOLPY_FLASHSIZE="{flash_mb}MB"',
             f'CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="{partition_file}"']
from micros_tooling.config.resources import board_psram_bytes
retained = [line for line in retained if "CONFIG_SPIRAM" not in line]
if board_psram_bytes(definition):
    retained += ["CONFIG_SPIRAM=y", "CONFIG_SPIRAM_BOOT_INIT=y", "CONFIG_SPIRAM_USE_CAPS_ALLOC=y", "CONFIG_SPIRAM_MEMTEST=y", "CONFIG_SPIRAM_SPEED_40M=y"]
else:
    retained += ["# CONFIG_SPIRAM is not set"]
if ota:
    retained = [line for line in retained if not any(key in line for key in
                ("CONFIG_MICROS_BASE_OTA", "CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE"))]
    retained += ["CONFIG_MICROS_BASE_OTA=y", "CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y"]
atomic_write(configuration, ("\n".join(retained) + "\n" + (credentials / "sdkconfig.management").read_text() + relay_settings).encode())
subprocess.run(
    [
        "idf.py",
        "-C",
        str(ROOT / "src/firmware/platforms/esp32/sdk"),
        "-B",
        str(build),
        "-D",
        "SDKCONFIG=" + str(configuration),
        "-D",
        "SDKCONFIG_DEFAULTS=" + ";".join(map(str, defaults)),
        "-D",
        "MICROS_CREDENTIALS_DIR=" + str(credentials),
        "-D",
        "MICROS_BOARD_FILE=" + str(board),
        "-D",
        "MICROS_RELAY_CREDENTIALS_DIR=" + (str(args.relay_credentials.resolve()) if args.relay_credentials else ""),
        "build",
    ],
    check=True,
)
