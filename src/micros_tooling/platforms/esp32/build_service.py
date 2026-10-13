#!/usr/bin/env python3
"""Build a freestanding flash or legacy RAM service against exported base slots."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import struct
from elftools.elf.elffile import ELFFile

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
from micros_tooling.storage.native_image import (
    envelope,
    TARGET_ESP32_XTENSA,
    CODE_SLOT_CAPACITY,
    DATA_SLOT_CAPACITY,
    WORD_BYTES,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def load_symbol_addresses(executable_path):
    with executable_path.open("rb") as stream:
        elf = ELFFile(stream)
        return {
            symbol.name: symbol["st_value"]
            for symbol in elf.get_section_by_name(".symtab").iter_symbols()
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variant", choices=["v1", "v2"], default="v1")
    parser.add_argument("--slot", type=int, choices=range(4))
    parser.add_argument("--source", type=Path, action="append")
    parser.add_argument("--include-directory", type=Path, action="append", default=[])
    parser.add_argument("--protobuf-directory", type=Path)
    parser.add_argument("--define", action="append", default=[])
    parser.add_argument("--descriptor-symbol", default="micros_descriptor")
    parser.add_argument("--arena", choices=["RAM", "PSRAM"], default="RAM")
    parser.add_argument("--stack-bytes", type=int, default=None,
                        help="Deployment stack budget in bytes (1..16384)")
    arguments = parser.parse_args()
    if arguments.stack_bytes is not None and not 1 <= arguments.stack_bytes <= 16384:
        parser.error("--stack-bytes must be between 1 and 16384")
    arguments.output.mkdir(parents=True, exist_ok=True)
    compiler = shutil.which("xtensa-esp32-elf-gcc")
    if not compiler:
        parser.error("Activate ESP-IDF v5.5.2 before building services")
    compiler_version = subprocess.check_output(
        [compiler, "--version"], text=True
    ).splitlines()[0]
    if "esp-14.2.0_20251107" not in compiler_version:
        parser.error("Expected the pinned ESP-IDF v5.5.2 compiler esp-14.2.0_20251107")
    # Link against reserved slots without linking service code into the firmware.
    firmware_symbols = load_symbol_addresses(arguments.firmware)
    if arguments.arena == "PSRAM" and ("micros_arena_placement_version" not in firmware_symbols or "esp_psram_extram_add_to_heap_allocator" not in firmware_symbols):
        parser.error("Base does not enable PSRAM arena support")
    suffix = "" if arguments.slot is None else str(arguments.slot)
    code_base = firmware_symbols["micros_code_slot" + suffix]
    data_base = firmware_symbols["micros_data_slot" + suffix]
    # Full runtime reserves four 8 KiB/4 KiB slots; legacy M1 uses one larger slot.
    code_capacity = CODE_SLOT_CAPACITY if arguments.slot is None else firmware_symbols.get("micros_service_code_capacity", 8192)
    data_capacity = DATA_SLOT_CAPACITY if arguments.slot is None else 4096
    rodata_base = firmware_symbols.get("micros_rodata_slot" + suffix, 0)
    data_capacity = firmware_symbols.get("micros_service_data_capacity", data_capacity)
    linker_script = arguments.output / "service.ld"
    # Keep only the ABI descriptor in writable data; all other constants get a
    # byte-addressable flash alias of the same physical service payload.
    descriptor_section = f"KEEP(*(.rodata.{arguments.descriptor_symbol}))"
    text = f".text 0x{code_base:x} : ALIGN(4) {{ *(.literal .literal.*) *(.text .text.*) . = ALIGN(4); }}"
    data = f".data 0x{data_base:x} : ALIGN(4) {{ {descriptor_section} "
    data += ("" if rodata_base else "*(.rodata .rodata.*) ")
    data += "*(.data .data.*) . = ALIGN(4); }"
    rodata = (f".rodata (0x{rodata_base:x} + SIZEOF(.text)) : ALIGN(4) {{ *(.rodata .rodata.*) . = ALIGN(4); }}"
              if rodata_base else "")
    linker_script.write_text(
        f"ENTRY(micros_service_query)\nSECTIONS {{ {text} {data} "
        ".bss (NOLOAD) : ALIGN(4) { *(.bss .bss.*) *(COMMON) . = ALIGN(4); } "
        f"{rodata} /DISCARD/ : {{ *(.comment) *(.note*) *(.eh_frame*) }} }}\n"
        f'ASSERT(SIZEOF(.text){" + SIZEOF(.rodata)" if rodata_base else ""} <= {code_capacity}, "code slot overflow")\n'
        f'ASSERT(SIZEOF(.data) + SIZEOF(.bss) <= {data_capacity}, "data slot overflow")\n'
    )
    object_path = arguments.output / "service.o"
    executable_path = arguments.output / "service.elf"
    compiler_flags = [
        "-Os",
        "-ffreestanding",
        "-ffunction-sections",
        "-fdata-sections",
        "-fno-builtin",
        "-fno-common",
        "-fno-stack-protector",
        "-fno-unwind-tables",
        "-fno-asynchronous-unwind-tables",
        "-fno-jump-tables",
        "-fno-tree-switch-conversion",
        "-fno-tree-loop-distribute-patterns",
        f"-falign-functions={WORD_BYTES}",
        "-mtext-section-literals",
        "-mlongcalls",
        "-Wall",
        "-Wextra",
        "-Werror",
    ]
    sources = arguments.source or [REPOSITORY_ROOT / "examples/hello-service/src/service.c"]
    if arguments.protobuf_directory:
        from micros_tooling.config.protobuf import RUNTIME, RUNTIME_SOURCES
        sources = sources + sorted(arguments.protobuf_directory.glob("*.pb.c")) + RUNTIME_SOURCES
        arguments.include_directory += [arguments.protobuf_directory, RUNTIME]
    object_paths = []
    for index, source in enumerate(
        sources
        + [REPOSITORY_ROOT / "src/sdk/c/src/freestanding.c"]
    ):
        object_path = arguments.output / f"service{index}.o"
        is_cpp = source.suffix in (".cpp", ".cc", ".cxx")
        source_compiler = compiler.replace("-gcc", "-g++") if is_cpp else compiler
        language_flags = (
            ["-std=c++17", "-fno-exceptions", "-fno-rtti", "-fno-threadsafe-statics"]
            if is_cpp
            else ["-std=c17"]
        )
        subprocess.run(
            [
                source_compiler,
                *language_flags,
                *compiler_flags,
                "-I",
                str(REPOSITORY_ROOT / "src/sdk/abi/include"),
                "-I",
                str(REPOSITORY_ROOT / "src/sdk/c/include"),
                f"-DMICROS_SERVICE_TARGET={TARGET_ESP32_XTENSA}",
                f'-DMICROS_SERVICE_VARIANT="{arguments.variant}"',
                *["-I" + str(directory) for directory in arguments.include_directory],
                *["-D" + definition for definition in arguments.define],
                "-c",
                str(source),
                "-o",
                str(object_path),
            ],
            check=True,
        )
        # Section GC must not hide forbidden startup hooks or TLS before admission checks.
        with object_path.open("rb") as object_stream:
            object_elf = ELFFile(object_stream)
            forbidden = [section.name for section in object_elf.iter_sections()
                         if section["sh_size"] and (
                             section["sh_type"] in ("SHT_INIT_ARRAY", "SHT_FINI_ARRAY", "SHT_PREINIT_ARRAY")
                             or section["sh_flags"] & 0x400  # ELF SHF_TLS.
                             or section.name.startswith((".ctors", ".dtors")))]
            assert not forbidden, f"Unsupported initialization/TLS in {source}: {forbidden}"
        object_paths.append(object_path)
    subprocess.run(
        [
            compiler,
            "-nostdlib",
            "-Wl,--no-undefined",
            "-Wl,--gc-sections",
            "-Wl,-T," + str(linker_script),
            "-Wl,-Map," + str(arguments.output / "service.map"),
            *map(str, object_paths),
            "-lgcc",
            "-o",
            str(executable_path),
        ],
        check=True,
    )
    with executable_path.open("rb") as stream:
        elf = ELFFile(stream)
        # Reject output requiring unsupported on-device linking work.
        # The ESP32 profile is ELF32 little-endian Xtensa, linked executable output.
        assert (
            elf.elfclass == 32
            and elf.little_endian
            and (elf["e_machine"] == "EM_XTENSA")
            and (elf["e_type"] == "ET_EXEC")
        )
        assert not [
            symbol
            for symbol in elf.get_section_by_name(".symtab").iter_symbols()
            if symbol.name and symbol["st_shndx"] == "SHN_UNDEF"
        ], "unresolved imports"
        assert not [
            section
            for section in elf.iter_sections()
            if section["sh_type"] in ("SHT_REL", "SHT_RELA") and section["sh_size"]
        ], "runtime relocations"
        # ELF SHF_ALLOC is bit 1 (0x2): only text/data/BSS may occupy runtime memory.
        unsupported_sections = [
            section.name
            for section in elf.iter_sections()
            if section["sh_flags"] & 2
            and section["sh_size"]
            and (section.name not in ((".text", ".data", ".bss", ".rodata") if rodata_base else (".text", ".data", ".bss")))
        ]
        assert (
            not unsupported_sections
        ), f"unsupported allocated sections: {unsupported_sections}"
        code_payload = elf.get_section_by_name(".text").data()
        rodata_payload = elf.get_section_by_name(".rodata").data() if rodata_base else b""
        text_bytes = len(code_payload)
        code_payload += rodata_payload
        data_payload = elf.get_section_by_name(".data").data()
        bss = elf.get_section_by_name(".bss")
        bss_bytes = bss["sh_size"] if bss else 0
    descriptor_offset = (
        load_symbol_addresses(executable_path)[arguments.descriptor_symbol] - data_base
    )
    data_payload = bytearray(data_payload)
    struct.pack_into("<I", data_payload, descriptor_offset + 28, int(arguments.arena == "PSRAM"))
    if arguments.stack_bytes is not None:
        struct.pack_into("<I", data_payload, descriptor_offset + 24, arguments.stack_bytes)
    data_payload = bytes(data_payload)
    service_image = envelope(
        TARGET_ESP32_XTENSA,
        code_payload,
        data_payload,
        bss_bytes,
        code_base,
        data_base,
        descriptor_offset,
        rodata_base=rodata_base, rodata_bytes=len(rodata_payload),
    )
    (arguments.output / "service.mimg").write_bytes(service_image)
    readelf_tool = shutil.which("xtensa-esp32-elf-readelf")
    relocations = subprocess.check_output(
        [readelf_tool, "-r", str(object_path)], text=True
    )
    (arguments.output / "object-relocations.txt").write_text(relocations)
    report = {
        "compiler": compiler_version,
        "variant": arguments.variant,
        "code_base": hex(code_base),
        "data_base": hex(data_base),
        "code_bytes": len(code_payload),
        "data_bytes": len(data_payload),
        "bss_bytes": bss_bytes,
        "descriptor_offset": descriptor_offset,
        "runtime_relocations": 0,
        "strategy": "flash-mapped code/constants" if rodata_base else "link-time fixed RAM slot",
        "text_bytes": text_bytes, "rodata_bytes": len(rodata_payload),
        "flags": compiler_flags,
    }
    prefix = struct.unpack_from("<8I", data_payload, descriptor_offset)
    report["memory"] = dict(
        arena_bytes=prefix[4], arena_alignment=prefix[5], stack_bytes=prefix[6], arena=arguments.arena
    )
    report["slot"] = arguments.slot
    (arguments.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
