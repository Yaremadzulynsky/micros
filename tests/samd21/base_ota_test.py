"""Power-cut prefixes must never replace a valid boot selection with torn metadata."""
import ctypes,struct,subprocess,tempfile,unittest,zlib,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT / "src"))
from micros_tooling.platforms.samd21.layout import initial_record,migration_image
class BootTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();lib=Path(cls.tmp.name)/'record.dylib'
        subprocess.run(['cc','-shared','-fPIC',str(ROOT/'src/firmware/platforms/samd21/sdk/boot/record.c'),'-o',str(lib)],check=True)
        cls.lib=ctypes.CDLL(str(lib));cls.lib.samd_boot_latest.argtypes=[ctypes.c_void_p]
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def base(self):return struct.pack('<II',0x20008000,0x4101)+bytes(504)
    def latest(self,a,b):return self.lib.samd_boot_latest(ctypes.create_string_buffer(a+b))
    def test_power_cut_each_byte(self):
        old=initial_record(self.base());new=bytearray(old)
        struct.pack_into('<I',new,4,2);struct.pack_into('<I',new,16,1)
        struct.pack_into('<I',new,28,512);struct.pack_into('<I',new,56,zlib.crc32(new[:56]))
        for cut in range(65):
            torn=bytes(new[:cut])+b'\xff'*(64-cut)
            self.assertEqual(self.latest(old,torn),1 if cut==64 else 0)
    def test_corruption_and_empty(self):
        old=initial_record(self.base())
        self.assertEqual(self.latest(b'\xff'*64,b'\xff'*64),-1)
        for i in range(64):
            corrupt=bytearray(old);corrupt[i]^=1
            self.assertEqual(self.latest(bytes(corrupt),old),1)
    def test_migration_keeps_selector_and_settings_outside_slots(self):
        selector=struct.pack('<II',0x20008000,0x2009)+bytes(100)
        settings=bytes(range(256))*4
        image=migration_image(self.base(),selector,settings)
        self.assertEqual(image[:len(selector)],selector)
        self.assertEqual(image[0x1c00:0x2000],settings)
        self.assertEqual(image[0x2000:],self.base())
if __name__=='__main__':unittest.main()
