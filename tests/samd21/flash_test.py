"""Validate the two-record settings preservation used before USB base erasure."""
import argparse
from unittest.mock import Mock, patch
import struct
import sys
import unittest
import zlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from micros_tooling.platforms.samd21.flash import valid_settings, enter_bootloader
from micros_tooling.storage.packages import PackageError


class SettingsTests(unittest.TestCase):
    def test_broken_rpc_gives_physical_recovery_instructions_and_closes_port(self):
        device = argparse.Namespace(device='/mkr', pid=0x8054, serial_number='serial')
        remote = Mock()
        remote.request.side_effect = PackageError("RPC: {'result': -1, 'error': 'invalid RPC frame'}")
        with patch('micros_tooling.platforms.samd21.transport.SerialRemote', return_value=remote):
            with self.assertRaisesRegex(PackageError, 'Double-press.*--rebuild-base.*invalid RPC frame'):
                enter_bootloader(device, '/bossac')
        remote.serial.close.assert_called_once()

    def test_physical_bootloader_skips_broken_rpc(self):
        device = argparse.Namespace(device='/boot', vid=0x2341, pid=0x0054, location='usb-1')
        with patch('micros_tooling.platforms.samd21.flash.list_ports.comports', return_value=[device]), \
             patch('micros_tooling.platforms.samd21.transport.SerialRemote') as remote:
            self.assertEqual(enter_bootloader(device, '/bossac'), ['/bossac', '-p', '/boot', '-U', 'true'])
        remote.assert_not_called()

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
