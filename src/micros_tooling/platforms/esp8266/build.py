"""ESP8266 call0 images in the current app's mapped service window."""

from micros_tooling.platforms.esp8266.firmware import bind
from pathlib import Path
from elftools.elf.elffile import ELFFile
from micros_tooling.storage.packages import require
from micros_tooling.platforms.embedded.build import ROOT


def base_info(firmware):
    with Path(firmware).open("rb") as stream:
        elf = ELFFile(stream)
        require(
            elf.elfclass == 32 and elf.little_endian and elf["e_machine"] == "EM_XTENSA",
            "Expected ESP8266 base ELF",
        )
        symbols = {
            s.name: s["st_value"] for s in elf.get_section_by_name(".symtab").iter_symbols()
        }
        require(
            "embedded_data" in symbols and "embedded_profile" in symbols,
            "Base lacks ESP8266 services",
        )
    return dict(
        hash=bind(firmware),
        data_base=symbols["embedded_data"],
        target=6,
        board_profile="esp8266_4mb",
        data_bytes=1024,
        compiler_prefix="xtensa-lx106-elf-",
        compile_flags=["-mlongcalls", "-mtext-section-literals"],
        link_flags=["-mlongcalls", "-mtext-section-literals"],
        bank_base=0x402C0000,
        bank_bytes=0x20000,
        slot_bytes=0x7C00,
    )


def build(project, firmware, output, compiler_dir, bank, board=None, overlay=None):
    from micros_tooling.platforms.embedded.build import build as build_embedded

    return build_embedded(
        project, base_info(firmware), output, compiler_dir, bank, board, overlay
    )
