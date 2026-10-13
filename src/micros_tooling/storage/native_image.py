#!/usr/bin/env python3
"""M1 image envelope, not the final deployment package format.

Wire values mirror src/firmware/kernel/loader/image.h; change both when the format changes.
"""
import argparse
from enum import IntEnum
from pathlib import Path
import struct
import zlib
import platform
import sys

# Sixteen little-endian 32-bit words: twelve fields and four reserved zero words.
# Explicit packing avoids the host's native pointer width and structure padding.
WORD_BYTES = 4
HEADER_STRUCT = struct.Struct('<16I')
HEADER_BYTES = HEADER_STRUCT.size  # 16 * 4 = 64 bytes; not a RAM allocation limit.
IMAGE_MAGIC = 0x3152434D  # Little-endian bytes spell "MCR1".
FORMAT_VERSION = 1  # First M1 envelope format, distinct from the service ABI.
ABI_MAJOR = 0  # Experimental; no stable released ABI is promised yet.
ABI_REVISION = 7  # Runtime-owned coordination; exact native ABI match required.
TARGET_MACOS_ARM64 = 1  # Project-assigned ABI profile IDs, not CPU register values.
TARGET_ESP32_XTENSA = 2
# IDs identify distinct native calling conventions; reject unsupported developer hosts.
_HOST_PROFILES = {("darwin", "arm64"): 1, ("linux", "aarch64"): 3, ("linux", "x86_64"): 4}
NATIVE_HOST_TARGET = _HOST_PROFILES.get((sys.platform, platform.machine()))
if NATIVE_HOST_TARGET is None:
    raise RuntimeError("Supported hosts: macOS ARM64, Linux ARM64 or Linux x86-64")


class HeaderOffset(IntEnum):
    """Byte offsets follow the word order in the format-1 specification."""
    MAGIC = 0 * WORD_BYTES
    FORMAT = 1 * WORD_BYTES
    TARGET = 2 * WORD_BYTES
    ABI_MAJOR = 3 * WORD_BYTES
    ABI_REVISION = 4 * WORD_BYTES
    CODE_BASE = 5 * WORD_BYTES
    DATA_BASE = 6 * WORD_BYTES
    CODE_BYTES = 7 * WORD_BYTES
    DATA_BYTES = 8 * WORD_BYTES
    BSS_BYTES = 9 * WORD_BYTES
    DESCRIPTOR = 10 * WORD_BYTES
    CHECKSUM = 11 * WORD_BYTES
    RESERVED = 12 * WORD_BYTES


# MCU descriptor's eight uint32 fields precede its four 32-bit function pointers.
# These offsets are for corruption fixtures, not the host's pointer-sized layout.
DESCRIPTOR_ARENA_BYTES_OFFSET = 4 * WORD_BYTES
DESCRIPTOR_ARENA_ALIGNMENT_OFFSET = 5 * WORD_BYTES
DESCRIPTOR_INIT_HOOK_OFFSET = 8 * WORD_BYTES

# Fixed-slot experiment capacities mirror m1_limits.h. These are deliberately
# bounded reservations, not the chip's maximum RAM or this example's usage.
CODE_SLOT_CAPACITY = 16 * 1024
DATA_SLOT_CAPACITY = 8 * 1024


def envelope(target, code_payload, data_payload=b'', bss_bytes=0,
             code_base=0, data_base=0, descriptor_offset=0, *, rodata_base=0, rodata_bytes=0):
    header = HEADER_STRUCT.pack(
        IMAGE_MAGIC, 2 if rodata_base else FORMAT_VERSION, target, ABI_MAJOR, ABI_REVISION,
        code_base, data_base, len(code_payload), len(data_payload), bss_bytes,
        descriptor_offset, zlib.crc32(code_payload + data_payload),
        rodata_base, rodata_bytes, 0, 0,  # Format 2 read-only alias; format 1 stays unchanged.
    )
    return header + code_payload + data_payload


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('library', type=Path)
    parser.add_argument('output', type=Path)
    arguments = parser.parse_args()
    arguments.output.write_bytes(envelope(NATIVE_HOST_TARGET, arguments.library.read_bytes()))
