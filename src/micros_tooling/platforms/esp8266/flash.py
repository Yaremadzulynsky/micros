"""Explicit USB installation; no flash backup or full-chip erase."""

from pathlib import Path
import shutil
import struct
import subprocess
import zlib
from micros_tooling.storage.packages import require
from .firmware import bind
from .transport import find_port


def flash(firmware, port=None):
    firmware = Path(firmware)
    bind(firmware)
    directory = firmware.parent
    executable = shutil.which("esptool.py") or shutil.which("esptool")
    require(executable, "Install esptool for USB flashing")
    prefix = struct.pack("<6I", 0x3642544D, 1, 0, 0xFFFFFFFF, 0xFFFFFFFF, 0)
    journal = prefix + struct.pack("<II", zlib.crc32(prefix), 0x54494D43)
    record = directory / "boot-state-initial.bin"
    record.write_bytes(journal + b"\xff" * (8192 - len(journal)))
    files = [
        (0, directory / "bootloader/bootloader.bin"),
        (0x8000, directory / "partition_table/partition-table.bin"),
        (0x10000, firmware.with_suffix(".bin")),
        (0x100000, record),
    ]
    require(
        all(p.is_file() for _, p in files),
        "USB installation needs the complete base build directory",
    )
    command = [
        executable,
        "--chip",
        "esp8266",
        "--port",
        find_port(port).device,
        "--baud",
        "115200",
        "write_flash",
        "--flash_mode",
        "dio",
        "--flash_freq",
        "40m",
        "--flash_size",
        "4MB",
    ]
    for address, path in files:
        command.extend((hex(address), str(path)))
    subprocess.run(command, check=True)
