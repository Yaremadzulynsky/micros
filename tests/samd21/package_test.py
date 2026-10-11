#!/usr/bin/env python3
"""Cross-check ARM envelopes and SHA-256 against independent host implementations."""
import ctypes
import hashlib
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zlib
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT / "src"))
from micros_tooling.storage.packages import image_metadata, PackageError
from micros_tooling.storage.native_image import envelope
from micros_tooling.platforms.samd21.board import definition

class Image(ctypes.Structure):
    _fields_=[(name,ctypes.c_uint32) for name in ('target','code_base','data_base','code_bytes','data_bytes','bss_bytes','descriptor_offset','rodata_base','rodata_bytes')]
class Hash(ctypes.Structure):
    _fields_=[('h',ctypes.c_uint32*8),('bytes',ctypes.c_uint64),('block',ctypes.c_ubyte*64),('used',ctypes.c_size_t)]

class Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();lib=Path(cls.tmp.name)/'checks.so'
        subprocess.run(['cc','-std=c17','-shared','-fPIC','-Wall','-Wextra','-Werror','-I'+str(ROOT/'src/sdk/abi/include'),
                        str(ROOT/'src/firmware/kernel/loader/image.c'),str(ROOT/'src/firmware/kernel/loader/elf.c'),str(ROOT/'src/firmware/kernel/hash/sha256.c'),'-o',str(lib)],check=True)
        cls.lib=ctypes.CDLL(str(lib));cls.lib.micros_image_validate.restype=ctypes.c_char_p
        cls.lib.micros_image_validate.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint32,ctypes.POINTER(Image)]
        cls.lib.micros_sha256_init.argtypes=[ctypes.POINTER(Hash)]
        cls.lib.micros_sha256_update.argtypes=[ctypes.POINTER(Hash),ctypes.c_void_p,ctypes.c_size_t]
        cls.lib.micros_sha256_finish.argtypes=[ctypes.POINTER(Hash),ctypes.c_void_p]
    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()
    def validate(self,data):
        parsed=Image();return self.lib.micros_image_validate(data,len(data),5,ctypes.byref(parsed))
    def test_sha256(self):
        for n in (0,1,55,56,63,64,65,127,128,1000,65536):
            data=bytes(i%251 for i in range(n))
            for step in (1,17,256):
                state=Hash();self.lib.micros_sha256_init(ctypes.byref(state))
                for start in range(0,n,step):
                    chunk=data[start:start+step];self.lib.micros_sha256_update(ctypes.byref(state),chunk,len(chunk))
                result=ctypes.create_string_buffer(32);self.lib.micros_sha256_finish(ctypes.byref(state),result)
                self.assertEqual(result.raw,hashlib.sha256(data).digest())
    def test_valid_envelope(self):
        data=envelope(5,b'\x00'*8,b'\x00'*48,4,0x21040,0x20001000,0)
        self.assertIsNone(self.validate(data));self.assertEqual(image_metadata(data)['target'],5)
    def test_corruption(self):
        good=envelope(5,b'\x00'*8,b'\x00'*48,4,0x21040,0x20001000,0)
        for offset,value in ((0,0),(4,2),(8,2),(16,4),(20,0x21041),(28,4096),(40,4),(48,1),(44,0)):
            data=bytearray(good);struct.pack_into('<I',data,offset,value)
            self.assertIsNotNone(self.validate(bytes(data)),offset)
        for n in (0,32,63,len(good)-1):self.assertIsNotNone(self.validate(good[:n]))
    def test_mkr_pin_mapping(self):
        board=definition(dict(profile='arduino_mkr_wifi_1010',gpio={'led':{'pin':6,'direction':'output'}}))
        self.assertEqual(board['gpio'][0]['pin'],6)
        with self.assertRaises(PackageError):definition(dict(profile='arduino_mkr_wifi_1010',gpio={'radio':{'pin':30,'direction':'output'}}))

if __name__=='__main__':unittest.main()
