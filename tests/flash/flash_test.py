#!/usr/bin/env python3
"""Exercise wire compatibility and bank mapping lifetime on the host."""
import ctypes
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from micros_tooling.storage.native_image import envelope
from micros_tooling.storage.packages import image_metadata, PackageError

class FlashTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.output = Path(cls.tmp.name)
        cls.includes = ["-I"+str(ROOT/p) for p in (
            "tests/flash/mocks", "src/sdk/abi/include", "src/firmware/contracts/include", "src/firmware/controller/include", "src/firmware/kernel/loader",
            "src/firmware/kernel/runtime", "src/firmware/kernel/deployment", "src/firmware/platforms/esp32/src/support")]
        lib = cls.output / "image.so"
        subprocess.run(["cc", "-shared", "-fPIC", *cls.includes,
                        str(ROOT/"src/firmware/kernel/loader/image.c"), str(ROOT/"src/firmware/kernel/loader/elf.c"),
                        "-o", str(lib)], check=True)
        cls.lib = ctypes.CDLL(str(lib))
        cls.lib.micros_image_validate.restype = ctypes.c_char_p
        cls.lib.micros_image_validate.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_void_p]
    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()
    def validate(self, image):
        return self.lib.micros_image_validate(image, len(image), 2, ctypes.create_string_buffer(128))
    def image(self):
        return envelope(2, b'\0'*32, b'\0'*48, code_base=0x40101040,
                        data_base=0x3ffb0000, rodata_base=0x3f421040, rodata_bytes=16)
    def test_flash_and_legacy(self):
        for image in (self.image(), envelope(2,b'\0'*32,b'\0'*48,code_base=0x40080000,data_base=0x3ffb0000)):
            self.assertIsNone(self.validate(image)); image_metadata(image)
    def test_corrupt_flash_layout(self):
        for word,value in ((1,3),(12,0),(12,1),(12,0xfffffff0),(13,3),(13,32),(13,36),(14,1),(15,1)):
            image=bytearray(self.image()); struct.pack_into('<I',image,word*4,value); image=bytes(image)
            self.assertIsNotNone(self.validate(image), (word,value))
            with self.assertRaises(PackageError): image_metadata(image)
    def test_truncated_or_corrupt_payload(self):
        for image in (self.image()[:-1], self.image()+b'\0', self.image()[:-1]+b'x'):
            self.assertIsNotNone(self.validate(image))
            with self.assertRaises(PackageError): image_metadata(image)
    def test_mapping_lifetime(self):
        output=self.output/'storage-test'
        subprocess.run(['cc','-std=c17','-Wall','-Wextra','-Werror',*self.includes,
                        *[str(ROOT/p) for p in ('tests/flash/storage_test.c','src/firmware/platforms/esp32/src/storage.c',
                        'src/firmware/kernel/deployment/activation.c','src/firmware/kernel/loader/image.c','src/firmware/kernel/loader/elf.c')],
                        '-o',str(output)],check=True)
        subprocess.run([str(output)],check=True)
if __name__=='__main__': unittest.main()
