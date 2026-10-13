"""Bind the SDK image to its exact service-linking ELF and seal its checksums."""

import hashlib
import struct
from pathlib import Path
from elftools.elf.elffile import ELFFile
from micros_tooling.storage.packages import require


def bind(firmware, *, write=False):
    firmware = Path(firmware)
    digest = hashlib.sha256(firmware.read_bytes()).digest()
    with firmware.open("rb") as stream:
        elf = ELFFile(stream)
        symbols = elf.get_section_by_name(".symtab").get_symbol_by_name("esp_app_desc")
        require(bool(symbols), "Base lacks an application descriptor")
        address = symbols[0]["st_value"]
        entry = elf["e_entry"]
        sections = [
            (s.name, s["sh_addr"], s.data())
            for s in elf.iter_sections()
            if s["sh_type"] == "SHT_PROGBITS" and s["sh_flags"] & 2 and s["sh_size"]
        ]
    binary = firmware.with_suffix(".bin")
    data = bytearray(binary.read_bytes())
    require(len(data) >= 48 and data[0] == 0xE9, "Invalid ESP8266 image")
    offset, descriptor, segments, mappings = 8, None, [], []
    require(struct.unpack_from("<I", data, 4)[0] == entry, "Image entry differs from ELF")
    for _ in range(data[1]):
        require(offset + 8 <= len(data), "Truncated image segment")
        start, size = struct.unpack_from("<II", data, offset)
        offset += 8
        require(offset + size <= len(data), "Truncated image data")
        segments.append((offset, size))
        mappings.append((start, offset, size))
        if start <= address and address + 256 <= start + size:
            descriptor = (
                address - 0x40210000 if start >= 0x40200000 else offset + address - start
            )
        offset += size
    end = (offset + 16) & ~15
    require(end + 32 == len(data), "Unexpected image trailer")
    require(hashlib.sha256(data[:end]).digest() == data[end:], "Invalid image digest")
    require(
        descriptor is not None and struct.unpack_from("<I", data, descriptor)[0] == 0xABCD5432,
        "Application descriptor does not match ELF",
    )
    checksum = 0xEF
    for start, size in segments:
        for byte in data[start : start + size]:
            checksum ^= byte
    require(data[end - 1] == checksum, "Invalid image checksum")
    # Verify every loadable section, allowing only the SDK's descriptor hash field
    # and the eight bytes replaced by the flash-rodata segment header.
    for name, start, content in sections:
        skip = 8 if name == ".flash.rodata" else 0
        start += skip
        content = content[skip:]
        location = (
            start - 0x40210000
            if start >= 0x40200000
            else next(
                (
                    position + start - base
                    for base, position, size in mappings
                    if base <= start and start + len(content) <= base + size
                ),
                None,
            )
        )
        require(
            location is not None and 0 <= location <= len(data) - len(content),
            "ELF section is absent from image: " + name,
        )
        observed = bytearray(data[location : location + len(content)])
        field = address + 144 - start
        if 0 <= field and field + 32 <= len(content):
            observed[field : field + 32] = content[field : field + 32]
        require(observed == content, "Image section differs from ELF: " + name)
    if write:
        data[descriptor + 144 : descriptor + 176] = digest
        checksum = 0xEF
        for start, size in segments:
            for byte in data[start : start + size]:
                checksum ^= byte
        data[end - 1] = checksum
        data[end:] = hashlib.sha256(data[:end]).digest()
        binary.write_bytes(data)
    else:
        require(
            data[descriptor + 144 : descriptor + 176] == digest,
            "Base binary is not bound to this ELF; finalize and flash the base first",
        )
    return digest
