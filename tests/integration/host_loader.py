"""Exercise independent loading, fresh state, and envelope rejection."""
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import zlib
# Test corruption at documented field positions, not arbitrary byte offsets.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from micros_tooling.storage.native_image import (HeaderOffset, HEADER_BYTES, WORD_BYTES,
    TARGET_MACOS_ARM64, TARGET_ESP32_XTENSA, DESCRIPTOR_ARENA_BYTES_OFFSET,
    DESCRIPTOR_ARENA_ALIGNMENT_OFFSET, DESCRIPTOR_INIT_HOOK_OFFSET)

# Deliberately incompatible/boundary values for rejection fixtures.
UNSUPPORTED_ABI_REVISION = 999  # Outside the current exact-match revision.
UINT32_MAX = 0xffffffff       # Exercises length/offset overflow boundaries.
ALIGNED_UINT32_MAX = UINT32_MAX - (WORD_BYTES - 1)  # Invalid offset, valid alignment.
EXPECTED_CYCLES = 2          # M1's first load plus clean reload.

# Eight seconds bounds the test process, above ordinary hook deadlines.
# The hung-hook case has a separate 5 s outer bound and expects timeout exit 2.
host_executable, build_directory = (sys.argv[1], Path(sys.argv[2]))
for variant in ('v1', 'v2'):
    result = subprocess.run([host_executable, str(build_directory / f'hello_{variant}.mimg')], capture_output=True, text=True, timeout=8)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count(f'hello {variant} init globals=7 bss=0 arena=0') == EXPECTED_CYCLES, result.stdout
    assert result.stdout.count('result=0') == EXPECTED_CYCLES and result.stdout.count('stop steps=3') == EXPECTED_CYCLES
valid_image = (build_directory / 'hello_v1.mimg').read_bytes()
# Short header, one missing payload byte, and one unexpected trailing byte.
invalid_images = {'short': valid_image[:12], 'truncated': valid_image[:-1], 'trailing': valid_image + b'X'}
for case_name, offset, value in [('target', HeaderOffset.TARGET, TARGET_ESP32_XTENSA), ('abi', HeaderOffset.ABI_REVISION, UNSUPPORTED_ABI_REVISION), ('previous_abi', HeaderOffset.ABI_REVISION, 1), ('length', HeaderOffset.CODE_BYTES, UINT32_MAX), ('offset', HeaderOffset.DESCRIPTOR, 4), ('reserved', HeaderOffset.RESERVED, 1)]:
    invalid_image = bytearray(valid_image)
    struct.pack_into('<I', invalid_image, offset, value)
    invalid_images[case_name] = invalid_image
invalid_image = bytearray(valid_image)
invalid_image[-1] ^= 1
invalid_images['checksum'] = invalid_image
# Mach-O: sizeofcmds at header byte 20; first command's size is at 32 + 4.
native_offsets = [('native_commands', HEADER_BYTES + 20), ('native_command_size', HEADER_BYTES + 32 + 4)] if sys.platform == 'darwin' else [('elf_program_offset', HEADER_BYTES + 32), ('elf_section_offset', HEADER_BYTES + 40)]
for case_name, offset in native_offsets:
    invalid_image = bytearray(valid_image)
    struct.pack_into('<I', invalid_image, offset, (UINT32_MAX - 7)) # Keep 8-byte command alignment while exceeding file bounds.
    struct.pack_into('<I', invalid_image, HeaderOffset.CHECKSUM, zlib.crc32(invalid_image[HEADER_BYTES:]))
    invalid_images[case_name] = invalid_image
with tempfile.TemporaryDirectory() as temporary_directory:
    for case_name, invalid_image in invalid_images.items():
        image_path = Path(temporary_directory) / f'{case_name}.mimg'
        image_path.write_bytes(invalid_image)
        result = subprocess.run([host_executable, str(image_path)], capture_output=True, text=True, timeout=8)
        assert result.returncode != 0 and 'REJECT' in result.stderr, (case_name, result)
        assert 'hello ' not in result.stdout, (case_name, result.stdout)
print(f'PASS two independent variants, two clean cycles each, {len(invalid_images)} rejected images')
result = subprocess.run([host_executable, str(build_directory / 'hung.mimg')], capture_output=True, text=True, timeout=5)
assert result.returncode == 2 and 'FATAL service deadline' in result.stderr, result
print('PASS uncooperative hook terminates the host runtime without reclaiming live code')
