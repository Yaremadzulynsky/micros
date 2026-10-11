#!/usr/bin/env python3
"""Requires the already flashed M1 harness; does not flash firmware."""
from pathlib import Path
import argparse
import struct
import sys
import zlib
# Test corruption at documented field positions, not arbitrary byte offsets.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from micros_tooling.storage.native_image import (HeaderOffset, HEADER_BYTES, WORD_BYTES,
    TARGET_MACOS_ARM64, TARGET_ESP32_XTENSA, DESCRIPTOR_ARENA_BYTES_OFFSET,
    DESCRIPTOR_ARENA_ALIGNMENT_OFFSET, DESCRIPTOR_INIT_HOOK_OFFSET)

# Deliberately incompatible/boundary values for rejection fixtures.
UNSUPPORTED_ABI_REVISION = 999  # Outside the only supported revision (1).
UINT32_MAX = 0xffffffff       # Exercises length/offset overflow boundaries.
ALIGNED_UINT32_MAX = UINT32_MAX - (WORD_BYTES - 1)  # Invalid offset, valid alignment.
EXPECTED_CYCLES = 2          # M1's first load plus clean reload.

sys.path.insert(0, str(Path(__file__).resolve().parent))
from serial_loader import connect, info, upload, run
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port', required=True)
parser.add_argument('--v1', type=Path, required=True)
parser.add_argument('--v2', type=Path, required=True)
parser.add_argument('--log', type=Path, required=True)
arguments = parser.parse_args()
transcript = []
with connect(arguments.port) as device:
    transcript.append(info(device))
    for variant, service_image_path in [('v1', arguments.v1), ('v2', arguments.v2)]:
        response = upload(device, service_image_path.read_bytes())
        transcript.append(response)
        assert 'LOADED' in response, response
        response = run(device)
        transcript.append(response)
        assert 'DONE' in response and response.count('result=0') == EXPECTED_CYCLES, response
        assert response.count(f'hello {variant} init globals=7 bss=0 arena=0') == EXPECTED_CYCLES, response
    valid_image = arguments.v1.read_bytes()
    invalid_images = {}
    for case_name, offset, value in [('target', HeaderOffset.TARGET, TARGET_MACOS_ARM64), ('abi', HeaderOffset.ABI_REVISION, UNSUPPORTED_ABI_REVISION), ('code_length', HeaderOffset.CODE_BYTES, UINT32_MAX), ('descriptor_offset', HeaderOffset.DESCRIPTOR, ALIGNED_UINT32_MAX), ('slot', HeaderOffset.CODE_BASE, struct.unpack_from('<I', valid_image, HeaderOffset.CODE_BASE)[0] + WORD_BYTES), ('reserved', HeaderOffset.RESERVED, 1)]:
        invalid_image = bytearray(valid_image)
        struct.pack_into('<I', invalid_image, offset, value)
        invalid_images[case_name] = invalid_image
    invalid_image = bytearray(valid_image)
    invalid_image[-1] ^= 1
    invalid_images['checksum'] = invalid_image
    invalid_images['truncated'] = valid_image[:-4]
    descriptor_file_offset = HEADER_BYTES + struct.unpack_from('<I', valid_image, HeaderOffset.CODE_BYTES)[0] + struct.unpack_from('<I', valid_image, HeaderOffset.DESCRIPTOR)[0]
    # 8192 exceeds the 4 KiB arena cap; 3 is not a power-of-two alignment;
    # a zero function pointer is an absent required hook.
    for case_name, offset, value in [('arena_budget', DESCRIPTOR_ARENA_BYTES_OFFSET, 8192), ('arena_alignment', DESCRIPTOR_ARENA_ALIGNMENT_OFFSET, 3), ('hook_pointer', DESCRIPTOR_INIT_HOOK_OFFSET, 0)]:
        invalid_image = bytearray(valid_image)
        struct.pack_into('<I', invalid_image, descriptor_file_offset + offset, value)
        struct.pack_into('<I', invalid_image, HeaderOffset.CHECKSUM, zlib.crc32(invalid_image[HEADER_BYTES:]))
        invalid_images[case_name] = invalid_image
    for case_name, invalid_image in invalid_images.items():
        response = upload(device, invalid_image)
        transcript.append(case_name + ': ' + response)
        assert 'REJECT ' in response and 'LOADED' not in response, (case_name, response)
    # A rejected transfer must not leave an older staged image runnable.
    response = run(device)
    transcript.append(response)
    assert 'REJECT ' in response, response
    transcript.append(info(device))
arguments.log.parent.mkdir(parents=True, exist_ok=True)
arguments.log.write_text(''.join(transcript))
print(''.join(transcript), end='')
print(f'PASS two variants, four clean cycles, {len(invalid_images)} invalid images and empty RUN rejected')
