"""Validate the two-record settings preservation used before USB base erasure."""
import struct
import sys
import unittest
import zlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from micros_tooling.platforms.samd21.flash import valid_settings


class SettingsTests(unittest.TestCase):
    def record(self):
        data = bytearray(b'\xff' * 1024)
        data[:308] = bytes(308)
        struct.pack_into('<II', data, 0, 0x3257464d, 1)
        struct.pack_into('<I', data, 304, zlib.crc32(data[:304]))
        struct.pack_into('<I', data, 448, 0x54494d43)
        return data

    def test_only_complete_checked_records_are_preserved(self):
        good = self.record()
        self.assertTrue(valid_settings(good))
        self.assertTrue(valid_settings(good[512:] + good[:512]))
        for offset in (0, 4, 16, 304, 448):
            bad = bytearray(good)
            bad[offset] ^= 1
            self.assertFalse(valid_settings(bad), offset)
        self.assertFalse(valid_settings(good[:512]))
        self.assertFalse(valid_settings(bytes(1024)))


if __name__ == '__main__':
    unittest.main()
