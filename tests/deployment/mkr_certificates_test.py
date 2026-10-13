"""NINA trust input bounds, installation receipts and exact-base restoration."""
import argparse
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import struct
import zlib
import unittest
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from micros_tooling.platforms.samd21 import certificates as c
from micros_tooling.fleet.server import server_main
from micros_tooling.storage.workspace import Workspace
from micros_tooling.storage.packages import PackageError


class CertificateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        with contextlib.redirect_stdout(io.StringIO()):
            server_main(['--state', str(self.root / 'server'), 'setup', '--host', '192.0.2.1'])
        self.cert = self.root / 'server/servercert.pem'
        self.state = Workspace(self.root / 'session')
        self.receipt = {}; self.save = Mock()
        self.device = argparse.Namespace(device='/mkr', vid=0x2341, pid=0x0054, location='usb-1')

    def test_public_bundle_deduplicates_and_rejects_private_keys_and_invalid_pem(self):
        raw = self.cert.read_bytes()
        expected = c.prepare_bundle(self.cert, self.root/'one.pem')
        self.cert.write_bytes(raw+raw)
        self.assertEqual(c.prepare_bundle(self.cert, self.root/'two.pem'), expected)
        self.assertEqual((self.root/'one.pem').read_bytes(), (self.root/'two.pem').read_bytes())
        for data in (b'not PEM', b'-----BEGIN PRIVATE KEY-----', b'-----BEGIN CERTIFICATE-----\nnotDER\n-----END CERTIFICATE-----'):
            self.cert.write_bytes(data)
            with self.assertRaises(PackageError): c.prepare_bundle(self.cert, self.root/'bad.pem')
        self.assertFalse((self.root/'bad.pem').exists())

    def test_large_bundle_rejected_before_device_mutation(self):
        self.cert.write_bytes(b''.join(b'-----BEGIN CERTIFICATE-----\n'+str(i).encode()+b'\n-----END CERTIFICATE-----\n' for i in range(65)))
        with patch.object(c.subprocess, 'run', return_value=argparse.Namespace(returncode=0)):
            with self.assertRaisesRegex(PackageError, 'trust budget'):
                c.prepare_bundle(self.cert, self.root/'large.pem')
        self.assertFalse((self.root/'large.pem').exists())

    def test_cached_download_is_checksum_verified(self):
        label, _ = c.ARCHIVES[('Darwin','arm64')]
        archive = self.root / 'build/toolchains' / ('arduino-fwuploader-'+c.VERSION) / (label+'.tar.gz')
        archive.parent.mkdir(parents=True);archive.write_bytes(b'corrupt archive')
        with patch.object(c.platform,'system',return_value='Darwin'), patch.object(c.platform,'machine',return_value='arm64'):
            with self.assertRaisesRegex(PackageError,'checksum mismatch'): c.uploader(self.root)

    def run_install(self, error=None, settings=bytes(1024)):
        def read_settings(command): Path(command[-1]).write_bytes(bytes(7168) + settings)
        with patch.object(c,'uploader',return_value=Path('/uploader')), \
             patch('micros_tooling.platforms.samd21.flash.select_device',return_value=self.device), \
             patch('micros_tooling.platforms.samd21.flash.bossac',return_value='/bossac'), \
             patch('micros_tooling.platforms.samd21.flash.enter_bootloader',return_value=['/bossac','-p','/boot','-U','true']), \
             patch('micros_tooling.platforms.samd21.flash.programmer',side_effect=read_settings), \
             patch('micros_tooling.deployment.enrollment.run_tool',side_effect=error) as run, \
             patch.object(c.list_ports,'comports',return_value=[self.device]), \
             patch('micros_tooling.platforms.samd21.flash.flash',return_value='/restored') as flash:
            try:
                return c.provision('/mkr', Path('/exact/base.elf'), 'serial', self.cert, self.state, self.receipt, self.save)
            finally:
                flash.assert_called_once_with(Path('/exact/base.elf'), '/mkr', 'serial', preserve_settings=False,
                                              settings_override=settings, helper_sketch=True)
                self.assertEqual(run.call_args.args[0][-2:], ['--file', str(self.state.root/'nina-trust.pem')])
                self.assertFalse(self.receipt['nina_restore_pending'])

    def test_success_records_trust_only_after_base_restore(self):
        self.assertEqual(self.run_install(), ('/restored',True))
        self.assertIn('nina_trust_sha256', self.receipt)
        with patch.object(c,'uploader') as uploader:
            self.assertEqual(c.provision('/mkr',Path('/exact/base.elf'),'serial',self.cert,self.state,self.receipt,self.save),('/mkr',False))
            uploader.assert_not_called()

    def test_valid_settings_are_restored_byte_for_byte(self):
        settings = bytearray(1024)
        struct.pack_into('<II', settings, 0, 0x3257464d, 7)
        settings[8:16] = b'testwifi'
        struct.pack_into('<I', settings, 304, zlib.crc32(settings[:304]))
        struct.pack_into('<I', settings, 448, 0x54494d43)
        self.run_install(settings=bytes(settings))
        self.assertEqual((self.state.root/'nina-settings.bin').read_bytes(), settings)

    def test_failed_upload_and_interrupt_restore_base_without_claiming_trust(self):
        for error in (PackageError('upload failed'), KeyboardInterrupt()):
            self.receipt = {}
            with self.assertRaises(type(error)): self.run_install(error)
            self.assertNotIn('nina_trust_sha256', self.receipt)

    def test_restore_failure_retains_pending_recovery(self):
        self.state.root.mkdir(parents=True, exist_ok=True)
        (self.state.root/'nina-settings.bin').write_bytes(bytes(1024))
        self.receipt['nina_restore_pending']=True
        with patch('micros_tooling.platforms.samd21.flash.flash',side_effect=PackageError('USB missing')):
            with self.assertRaises(PackageError):
                c.restore('/mkr',Path('/exact/base.elf'),'serial',self.state,self.receipt,self.save)
        self.assertTrue(self.receipt['nina_restore_pending'])
        self.save.assert_not_called()

if __name__ == '__main__': unittest.main()
