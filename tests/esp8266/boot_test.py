"""Exercise the actual selector with flash faults and resets between boots."""

import ctypes
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[2]
NONE = 0xFFFFFFFF


def record(seq=1, good=0, previous=NONE, candidate=NONE, attempts=0):
    fields = struct.pack("<6I", 0x3642544D, seq, good, previous, candidate, attempts)
    return fields + struct.pack("<II", zlib.crc32(fields), 0x54494D43)


class BootTest(unittest.TestCase):
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
