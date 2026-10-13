"""Exercise the actual selector with flash faults and resets between boots."""

import ctypes
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zlib
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
NONE = 0xFFFFFFFF


def record(seq=1, good=0, previous=NONE, candidate=NONE, attempts=0):
    fields = struct.pack("<6I", 0x3642544D, seq, good, previous, candidate, attempts)
    return fields + struct.pack("<II", zlib.crc32(fields), 0x54494D43)


class BootTest(unittest.TestCase):
    def test_vendor_static_task_reserves_tls_delete_callbacks(self):
        from micros_tooling.platforms.build_esp8266 import patch_static_task_layout, patch_static_task_check
        source = '''#if configNUM_THREAD_LOCAL_STORAGE_POINTERS > 0
void\t\t\t*pvDummy15[ configNUM_THREAD_LOCAL_STORAGE_POINTERS ];
#endif'''
        patched = patch_static_task_layout(source)
        with tempfile.TemporaryDirectory() as directory:
            unit = Path(directory) / 'layout.c'
            unit.write_text('struct static_task { int header;\n' + patched + '\n};\n' + '''
struct actual_task { int header;
#if configNUM_THREAD_LOCAL_STORAGE_POINTERS > 0
void *pointers[configNUM_THREAD_LOCAL_STORAGE_POINTERS];
#if configTHREAD_LOCAL_STORAGE_DELETE_CALLBACKS
void (*callbacks[configNUM_THREAD_LOCAL_STORAGE_POINTERS])(int, void *);
#endif
#endif
};
_Static_assert(sizeof(struct static_task)==sizeof(struct actual_task), "TCB size mismatch");
''')
            for count in (0, 1, 3):
                for enabled in (0, 1):
                    subprocess.run(['cc', '-std=c11', '-fsyntax-only',
                        f'-DconfigNUM_THREAD_LOCAL_STORAGE_POINTERS={count}',
                        f'-DconfigTHREAD_LOCAL_STORAGE_DELETE_CALLBACKS={enabled}', str(unit)], check=True)
        self.assertIn('_Static_assert(sizeof(StaticTask_t) == sizeof(TCB_t)',
                      patch_static_task_check('typedef tskTCB TCB_t;'))
        with self.assertRaises(ValueError):
            patch_static_task_layout('changed SDK')

    def test_static_stack_reservations_cannot_share_a_watchpoint_with_neighbours(self):
        from micros_tooling.platforms.build_esp8266 import validate_static_stacks
        symbols = {name: 0x3ffe8000 + index * 4096 for index, name in enumerate(
            ('_ZL16controller_stack', 'relay_stack', 'supervisor_stack', 'idle_stack$12', 'timer_stack$13'))}
        validate_static_stacks(symbols)
        for name in symbols:
            with self.assertRaisesRegex(ValueError, '16-byte-aligned'):
                validate_static_stacks(dict(symbols, **{name: symbols[name] + 4}))
        with self.assertRaises(ValueError):
            validate_static_stacks({})

    def test_warm_start_disarms_previous_stack_watchpoint_before_bss(self):
        from micros_tooling.platforms.build_esp8266 import patch_startup_watchpoint
        source = 'void call_start_cpu(size_t start_addr)\n{\n    for (p = &_bss_start; p < &_bss_end; p++) *p = 0;\n}\n'
        patched = patch_startup_watchpoint(source)
        self.assertLess(patched.index('dbreakc0'), patched.index('for (p'))
        self.assertIn('"a2", "memory"', patched)
        with self.assertRaises(ValueError):
            patch_startup_watchpoint(source.replace('call_start_cpu', 'changed_entry'))

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        (root / "esp8266").mkdir()
        (root / "esp8266/rom_functions.h").write_text(
            "#include <stddef.h>\n#define ESP_OK 0\nint SPIRead(size_t,void*,size_t);\nint SPIWrite(size_t,const void*,size_t);\nint SPIEraseSector(size_t);\n"
        )
        (root / "esp8266/eagle_soc.h").write_text("#define WDT_FEED() ((void)0)\n")
        (root / "test.c").write_text("""#include <string.h>
#include <stdint.h>
#include "selector.h"
static uint8_t flash[8192];static int cut=32;
int SPIRead(size_t a,void*p,size_t n){memcpy(p,flash+a-MICROS_BOOT_ADDRESS,n);return 0;}
int SPIWrite(size_t a,const void*p,size_t n){if(n>(unsigned)cut)n=cut;memcpy(flash+a-MICROS_BOOT_ADDRESS,p,n);return cut==32?0:-1;}
int SPIEraseSector(size_t sector){memset(flash+sector*4096-MICROS_BOOT_ADDRESS,255,4096);return 0;}
void setup(const void *a,const void*b,int count){memset(flash,255,sizeof(flash));memcpy(flash,a,32);memcpy(flash+4096,b,32);cut=count;}
int select_boot(void){return micros_boot_select(0);}
int latest(void){micros_boot_record_t r[2];memcpy(r,flash,32);memcpy(r+1,flash+4096,32);return micros_boot_latest(r);}
""")
        lib = root / "test.dylib"
        subprocess.run(
            [
                "cc",
                "-std=c17",
                "-shared",
                "-fPIC",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-I" + str(root),
                "-I" + str(ROOT / "src/firmware/platforms/esp8266/sdk/boot"),
                str(root / "test.c"),
                "-o",
                str(lib),
            ],
            check=True,
        )
        cls.lib = ctypes.CDLL(str(lib))
        cls.lib.setup.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setup(self, a, b=b"\xff" * 32, cut=32):
        self.lib.setup(ctypes.create_string_buffer(a), ctypes.create_string_buffer(b), cut)

    def test_initial_install(self):
        self.setup(b"\xff" * 32)
        self.assertEqual(self.lib.select_boot(), 0)
        self.assertEqual(self.lib.latest(), 0)

    def test_candidate_gets_one_attempt(self):
        self.setup(record(candidate=1))
        self.assertEqual(self.lib.select_boot(), 1)
        self.assertEqual(self.lib.select_boot(), 0)
        self.assertEqual(self.lib.select_boot(), 0)

    def test_confirmed_new_base(self):
        self.setup(record(), record(seq=4, good=1, previous=0))
        self.assertEqual(self.lib.select_boot(), 1)

    def test_torn_attempt_never_boots_candidate(self):
        for cut in range(32):
            self.setup(record(candidate=1), cut=cut)
            self.assertEqual(self.lib.select_boot(), 0)

    def test_torn_new_record_keeps_old(self):
        for cut in range(32):
            self.setup(record(), record(seq=2, candidate=1)[:cut] + b"\xff" * (32 - cut))
            self.assertEqual(self.lib.select_boot(), 0)

    def test_corrupted_record_ignored(self):
        for byte in range(32):
            bad = bytearray(record(seq=2, good=1))
            bad[byte] ^= 1
            self.setup(record(), bytes(bad))
            self.assertEqual(self.lib.select_boot(), 0)


if __name__ == "__main__":
    unittest.main()
