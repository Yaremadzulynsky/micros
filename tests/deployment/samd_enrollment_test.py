import argparse
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from micros_tooling.deployment import samd_enrollment as s, enrollment as e
from micros_tooling.storage.packages import PackageError, digest
from micros_tooling.storage.workspace import Workspace

from micros_tooling.platforms.samd21.flash import flash as real_flash
ID = 'ac1da4519140'


class SamdEnrollmentTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        firmware = self.root / 'base/firmware/runtime.ino.elf'
        firmware.parent.mkdir(parents=True)
        firmware.write_bytes(b'elf')
        (firmware.parent.parent / 'selector.bin').write_bytes(b'selector')
        self.prepared = dict(firmware=str(firmware), base_sha256='ab'*32, selector_sha256=digest(b'selector'))
        self.args = argparse.Namespace(name='mkr', firmware=None, detect=False, retry_flash=False, relay_credentials=None, json=True)
        self.remote = Mock()
        self.remote.raw.return_value = b'{"devices":[]}'
        device = argparse.Namespace(device='/mkr', vid=0x2341, pid=0x8054, serial_number='serial', location='usb-1')
        self.mocks = {}
        patches = {
            'micros_tooling.deployment.samd_enrollment.list_ports.comports': [device],
            'micros_tooling.communication.discovery.probe': dict(state='identified', platform='samd21', device_id=ID),
            'micros_tooling.deployment.samd_enrollment.prepare': self.prepared,
            'micros_tooling.platforms.samd21.build.base_info': dict(hash=bytes.fromhex('ab'*32)),
            'micros_tooling.platforms.samd21.flash.flash': '/mkr-new',
            'micros_tooling.deployment.samd_enrollment.read_identity': (ID, 'ab'*32),
            'micros_tooling.fleet.server.configured_remote': self.remote,
            'micros_tooling.deployment.enrollment.credentials': self.root,
            'micros_tooling.deployment.enrollment.connect_wifi': None,
            'micros_tooling.deployment.enrollment.verify_console': None,
        }
        for name, result in patches.items():
            patcher = patch(name, return_value=result)
            self.mocks[name.rsplit('.',1)[-1]] = patcher.start()
            self.addCleanup(patcher.stop)

    def enroll(self, roster=None):
        return s.enroll_mkr(self.args, '/mkr', self.root, Workspace(self.root), self.remote, roster or [])

    def state(self):
        return Workspace(self.root / 'onboarding' / ('mkr-usb-' + digest(b'usb-1')[:24]))

    def test_rebuild_archives_failed_attempt_and_prepares_new_artifacts(self):
        self.mocks['probe'].return_value = dict(state='unidentified')
        self.mocks['flash'].side_effect = PackageError('invalid RPC frame')
        with self.assertRaisesRegex(PackageError, 'invalid RPC frame'):
            self.enroll()
        previous = self.state().read('enrollment.json')
        self.mocks['flash'].side_effect = None
        self.args.rebuild_base = True
        self.assertTrue(self.enroll()['online'])
        self.assertEqual(self.mocks['prepare'].call_count, 2)
        sessions = [call.args[0] for call in self.mocks['prepare'].call_args_list]
        self.assertNotEqual(*sessions)
        archives = list((self.state().root / 'enrollment-history').glob('*.json'))
        self.assertEqual(len(archives), 1)
        self.assertEqual(self.state().read(archives[0].relative_to(self.state().root)), previous)
        self.assertTrue(Path(previous['firmware']).is_file())

    def test_retry_keeps_saved_firmware(self):
        self.mocks['probe'].return_value = dict(state='unidentified')
        self.mocks['flash'].side_effect = PackageError('invalid RPC frame')
        with self.assertRaises(PackageError):
            self.enroll()
        self.mocks['flash'].side_effect = None
        self.args.retry_flash = True
        self.assertTrue(self.enroll()['online'])
        self.assertEqual(self.mocks['prepare'].call_count, 1)

    def test_rebuild_rejects_confirmed_and_missing_attempts(self):
        self.args.rebuild_base = True
        with self.assertRaisesRegex(PackageError, 'unfinished enrollment'):
            self.enroll()
        self.mocks['flash'].assert_not_called()
        self.args.rebuild_base = False
        self.enroll()
        self.args.rebuild_base = True
        with self.assertRaisesRegex(PackageError, 'unfinished enrollment'):
            self.enroll()
        self.assertEqual(self.mocks['flash'].call_count, 1)

    def test_installs_without_backup_and_uses_reenumerated_port(self):
        result = self.enroll()
        self.assertTrue(result['online'])
        self.assertFalse(self.mocks['flash'].call_args.kwargs['preserve_settings'])
        self.assertEqual(self.mocks['connect_wifi'].call_args.args[1], '/mkr-new')

    def test_no_backup_programmer_path(self):
        firmware = self.root / 'base/firmware/runtime.ino.elf'
        firmware.with_suffix('.bin').write_bytes(b'base')
        boot = argparse.Namespace(device='/boot', vid=0x2341, pid=0x0054, serial_number=None, location='usb-1')
        app = argparse.Namespace(device='/app', vid=0x2341, pid=0x8054, serial_number='serial', location='usb-1')
        with patch('micros_tooling.platforms.samd21.flash.list_ports.comports', side_effect=[[boot], [boot], [app]]), \
             patch('micros_tooling.platforms.samd21.flash.shutil.which', return_value='/bossac'), \
             patch('micros_tooling.platforms.samd21.build.base_info', return_value=dict(hash=bytes.fromhex(digest(b'base')), flash_bytes=4, base_slot=0)), \
             patch('micros_tooling.platforms.samd21.layout.migration_image', return_value=b'image'), \
             patch('micros_tooling.platforms.samd21.flash.programmer') as programmer:
            self.assertEqual(real_flash(firmware, '/boot', preserve_settings=False), '/app')
        self.assertEqual(programmer.call_count, 1)
        self.assertIn('-w', programmer.call_args.args[0])
        self.assertFalse(any(arg.startswith('-r') for arg in programmer.call_args.args[0]))

    def test_erase_then_enroll_reinstalls_instead_of_reusing_old_receipt(self):
        from micros_tooling.deployment import erasure
        self.enroll()
        with patch('micros_tooling.storage.client.operator_directory', return_value=self.root), patch.object(e, 'choose_port', return_value='/mkr'), patch('micros_tooling.platforms.samd21.flash.erase_programmer', return_value='bossac'), patch('micros_tooling.platforms.samd21.flash.erase') as erase:
            result = erasure.erase(argparse.Namespace(command='erase', port='/mkr', yes=True, json=True))
        self.assertTrue(result['erased'])
        erase.assert_called_once()
        self.enroll()
        self.assertEqual(self.mocks['flash'].call_count, 2)
        self.assertEqual(self.mocks['prepare'].call_count, 2)

    def test_enrolled_controller_never_flashes(self):
        with self.assertRaisesRegex(PackageError, 'already enrolled'):
            self.enroll([dict(device_id=ID, name='mkr')])
        self.mocks['flash'].assert_not_called()

    def test_wrong_identity_stops_before_credentials(self):
        self.mocks['read_identity'].return_value = ('aabbccddeeff', 'ab'*32)
        with self.assertRaisesRegex(PackageError, 'identity changed'):
            self.enroll()
        self.mocks['credentials'].assert_not_called()

    def test_stock_sketch_identity_is_read_after_flash(self):
        self.mocks['probe'].return_value = dict(state='unidentified')
        self.assertEqual(self.enroll()['device_id'], ID)

    def test_cancel_cleans_dashboard_and_resume_does_not_reflash(self):
        self.mocks['connect_wifi'].side_effect = KeyboardInterrupt()
        with self.assertRaises(e.EnrollmentCancelled):
            self.enroll()
        self.mocks['connect_wifi'].side_effect = None
        self.assertTrue(self.enroll()['online'])
        self.assertEqual(self.mocks['flash'].call_count, 1)


if __name__ == '__main__':
    unittest.main()
