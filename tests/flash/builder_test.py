#!/usr/bin/env python3
"""Cross-link all four slots, proving large constants fit outside a 1 KiB RAM slot."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from elftools.elf.elffile import ELFFile
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT / "src"))
from micros_tooling.storage.packages import image_metadata
from micros_tooling.platforms.esp32.build_service import load_symbol_addresses
firmware=Path(sys.argv[1]).resolve()
base=load_symbol_addresses(firmware)
assert base['micros_service_data_capacity']==1024
with tempfile.TemporaryDirectory() as temporary:
    for slot in range(4):
        out=Path(temporary)/str(slot)
        subprocess.run([sys.executable,str(ROOT/'src/micros_tooling/platforms/esp32/build_service.py'),
                        '--firmware',str(firmware),'--output',str(out),'--slot',str(slot),
                        '--source',str(ROOT/'tests/flash/service.c')],check=True,stdout=subprocess.DEVNULL)
        info=image_metadata((out/'service.mimg').read_bytes())
        assert info['rodata_bytes']>=2048
        assert info['data_bytes']+info['bss_bytes']<128
        assert info['rodata_base']==base[f'micros_rodata_slot{slot}']
        symbols=load_symbol_addresses(out/'service.elf')
        assert info['rodata_base'] <= symbols['table'] < info['rodata_base']+info['code_bytes']
        assert info['data_base'] <= symbols['index_value'] < info['data_base']+1024
        assert info['data_base'] <= symbols['mutable_value'] < info['data_base']+1024
        with (out/'service.elf').open('rb') as f:
            elf=ELFFile(f)
            assert elf.get_section_by_name('.text')['sh_addr']==info['code_base']
            assert elf.get_section_by_name('.rodata')['sh_addr']==info['rodata_base']+info['code_bytes']-info['rodata_bytes']
print('Four flash service slots: code/constants in flash, mutable data in RAM; passed')
