"""MKR ELF identity and ARM toolchain settings for the shared embedded builder."""
import hashlib
from pathlib import Path
from elftools.elf.elffile import ELFFile
from micros_tooling.storage.packages import require
from micros_tooling.platforms.embedded.build import ROOT, build_image

def base_info(firmware):
    with Path(firmware).open('rb') as stream:
        elf = ELFFile(stream)
        require(elf.elfclass == 32 and elf.little_endian and elf['e_machine'] == 'EM_ARM', 'Expected SAMD21 base ELF')
        symbols = {s.name: s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
        require('micros_samd21_profile' in symbols and 'micros_samd21_data' in symbols, 'Base lacks SAMD21 dynamic service support')
        end = symbols['__etext'] + symbols['__data_end__'] - symbols['__data_start__']
        origin=symbols.get('__text_start__',0x2000)
        require(origin in (0x2000,0x4000,0x18000), 'Unknown SAMD base slot')
        require(origin < end <= (0x1e000 if origin==0x2000 else origin+0x14000), 'Base overlaps service storage')
        data = bytearray(end - origin)
        for segment in elf.iter_segments():
            address = segment['p_paddr']
            if segment['p_type'] == 'PT_LOAD' and segment['p_filesz'] and address < end:
                content = segment.data()
                start, stop = max(address, origin), min(address + len(content), end)
                if start < stop:
                    data[start - origin:stop - origin] = content[start - address:stop - address]
        return dict(target=5, board_profile='arduino_mkr_wifi_1010', data_bytes=512, compiler_prefix='arm-none-eabi-', compile_flags=['-mcpu=cortex-m0plus','-mthumb','-mfloat-abi=soft'], link_flags=['-mcpu=cortex-m0plus','-mthumb'], hash=hashlib.sha256(data).digest(), data_base=symbols['micros_samd21_data'], flash_bytes=len(data),
                    origin=origin, base_slot=(origin-0x4000)//0x14000 if origin!=0x2000 else None,
                    bank_base=0x20000 if origin==0x2000 else 0x2c000,
                    bank_bytes=65536 if origin==0x2000 else 40960,slot_bytes=15360 if origin==0x2000 else 9216)


def build(project, firmware, output, compiler_dir, bank, board=None, overlay=None):
    from micros_tooling.platforms.embedded.build import build as build_embedded
    return build_embedded(project,base_info(firmware),output,compiler_dir,bank,board,overlay)
