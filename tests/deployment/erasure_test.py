"""Destructive operations require exact identity and server removal first."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from micros_tooling.deployment import erasure as er
from micros_tooling.storage.workspace import Workspace
from micros_tooling.storage.packages import PackageError

BOARD = dict(platform='esp8266', chip='ESP8266EX', device_id='f4cfa2d08ce3', flash_mb=4)


class ErasureTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.state = Workspace(self.root / 'onboarding' / BOARD['device_id'])
        self.state.write('enrollment.json', dict(board=BOARD, flashed=True, name='desk'))
        self.remote = Mock()
        self.remote.raw.side_effect = [b'{"devices":[{"device_id":"f4cfa2d08ce3","name":"desk"}]}', b'{}', b'{"devices":[]}']
        for target, value in [('micros_tooling.storage.client.operator_directory', self.root),
                              ('micros_tooling.fleet.server.configured_remote', self.remote),
                              ('micros_tooling.deployment.enrollment.choose_port', '/fake'),
                              ('micros_tooling.deployment.enrollment.probe', BOARD),
                              ('micros_tooling.deployment.enrollment.esptool', ['esptool'])]:
            p = patch(target, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        self.events = []
        def tool(command, *a, **kw):
            if 'read_flash' in command:
                path = Path(command[-1])
                path.write_bytes((b'\xff' if path.name == 'after-erase.bin' else b'\x12') * (4 * 1048576))
            if 'erase_flash' in command:
                self.assertEqual(self.remote.raw.call_count, 3)
                self.assertEqual(self.state.read('enrollment.json'), {})
            self.events.append(command)
        p = patch.object(er.e, 'run_tool', side_effect=tool)
        self.tool = p.start()
        self.addCleanup(p.stop)
        self.args = argparse.Namespace(port='/fake', yes=True, json=True)

    def test_erase_keeps_history_without_readback(self):
        result = er.erase(self.args)
        self.assertTrue(result['erased'])
        session = Path(result['session'])
        self.assertTrue(Workspace(session).read('previous-enrollment.json')['flashed'])
        self.assertFalse((session / 'before-erase.bin').exists())
        self.assertIn('erase_flash', self.events[0])
        self.assertFalse(any('read_flash' in c for c in self.events))
        self.assertEqual(sum('erase_flash' in c for c in self.events), 1)
        self.assertTrue(self.state.read('erase.json')['complete'])
        self.assertEqual([c.args[1] for c in self.remote.raw.call_args_list], ['/v1/devices', '/v1/revoke', '/v1/devices'])

    def test_revoke_failure_never_erases(self):
        self.remote.raw.side_effect = [b'{"devices":[]}', TimeoutError('unavailable')]
        with self.assertRaises(TimeoutError):
            er.erase(self.args)
        self.assertFalse(any('erase_flash' in c for c in self.events))
        self.assertTrue(self.state.read('enrollment.json')['flashed'])

    def test_remaining_console_entry_never_erases(self):
        roster = b'{"devices":[{"device_id":"f4cfa2d08ce3","name":"desk"}]}'
        self.remote.raw.side_effect = [roster, b'{}', roster]
        with self.assertRaisesRegex(PackageError, 'remains enrolled'):
            er.erase(self.args)
        self.assertFalse(any('erase_flash' in c for c in self.events))

    def test_controller_selection_cancellation_has_no_mutations(self):
        with patch.object(er.e, 'choose_port', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                er.erase(self.args)
        self.tool.assert_not_called()
        self.remote.raw.assert_not_called()

    def test_esp32_erase_requires_no_confirmation(self):
        self.args.yes = False
        board = dict(BOARD, platform='esp32', chip='ESP32')
        with patch.object(er.e, 'probe', return_value=board), patch('builtins.input', side_effect=AssertionError('unexpected confirmation')):
            self.assertTrue(er.erase(self.args)['erased'])
        self.assertIn('esp32', self.events[0])

    def test_esp8266_erase_without_confirmation_does_not_repeat_rom_probe(self):
        self.args.yes = False
        with patch.object(er.e, 'probe', side_effect=[BOARD]) as probe, \
             patch.object(er.e, 'interactive', return_value=True), \
             patch('builtins.input', side_effect=AssertionError('unexpected confirmation')) as confirm:
            result = er.erase(self.args)
        self.assertTrue(result['erased'])
        probe.assert_called_once_with('/fake')
        confirm.assert_not_called()
        self.assertEqual(sum('erase_flash' in c for c in self.events), 1)

    def test_resumed_erase_rejects_changed_initial_identity(self):
        self.state.write('erase.json', dict(board=dict(BOARD, flash_mb=8),
                                         session=str(self.state.root / 'erasures/interrupted')))
        with self.assertRaisesRegex(PackageError, 'changed'):
            er.erase(self.args)
        self.tool.assert_not_called()
        self.assertEqual(self.remote.raw.call_count, 1)

    def test_failed_erase_cannot_report_success(self):
        self.tool.side_effect = PackageError('Chip erase failed')
        with self.assertRaisesRegex(PackageError, 'Chip erase failed'):
            er.erase(self.args)
        self.assertFalse(self.state.read('erase.json').get('complete', False))

    def test_resume_preserves_receipt_without_backup(self):
        original = self.tool.side_effect
        def interrupted(command, *a, **kw):
            if 'erase_flash' in command:
                raise TimeoutError('USB disconnected')
            original(command, *a, **kw)
        self.tool.side_effect = interrupted
        with self.assertRaises(TimeoutError):
            er.erase(self.args)
        pending = self.state.read('erase.json')
        session = Path(pending['session'])
        self.assertFalse((session / 'before-erase.bin').exists())
        self.tool.side_effect = original
        self.remote.raw.reset_mock()
        self.remote.raw.side_effect = [b'{"devices":[]}', b'{}', b'{"devices":[]}']
        result = er.erase(self.args)
        self.assertEqual(result['session'], str(session))
        self.assertFalse((session / 'before-erase.bin').exists())
        self.assertTrue(Workspace(session).read('previous-enrollment.json')['flashed'])

    def test_old_partial_backup_does_not_block_erase(self):
        session = self.state.root / 'erasures' / 'interrupted-old-version'
        session.mkdir(parents=True)
        partial = session / 'before-erase.partial'
        partial.write_bytes(b'incomplete old backup')
        self.state.write('erase.json', dict(board=BOARD, session=str(session), backup_sha256='obsolete'))
        result = er.erase(self.args)
        self.assertTrue(result['erased'])
        self.assertIn('erase_flash', self.events[0])
        self.assertEqual(partial.read_bytes(), b'incomplete old backup')


class SamdErasureTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.board = dict(platform='samd21', chip='SAMD21G18A', device_id='ac1da4519140', flash_mb=.25)
        self.device = argparse.Namespace(device='/mkr', vid=0x2341, pid=0x8054, serial_number='serial', location='usb-1')
        from micros_tooling.storage.packages import digest
        self.usb = Workspace(self.root / 'onboarding' / ('mkr-usb-' + digest(b'usb-1')[:24]))
        self.usb.write('enrollment.json', dict(board=self.board, flashed=True, confirmed=True))
        self.old = Workspace(self.root / 'onboarding/mkr-usb-old-port')
        self.old.write('enrollment.json', dict(board=self.board, flashed=True))
        self.other = Workspace(self.root / 'onboarding/mkr-usb-other')
        self.other.write('enrollment.json', dict(board=dict(self.board, device_id='aabbccddeeff'), flashed=True))
        self.remote = Mock()
        self.remote.raw.side_effect = [b'{"devices":[]}', b'{}', b'{"devices":[]}']
        patches = {
            'micros_tooling.storage.client.operator_directory': self.root,
            'micros_tooling.fleet.server.configured_remote': self.remote,
            'micros_tooling.deployment.enrollment.choose_port': '/mkr',
            'micros_tooling.deployment.samd_enrollment.is_mkr': True,
            'micros_tooling.deployment.samd_enrollment.read_identity': (self.board['device_id'], 'ab'*32),
            'micros_tooling.platforms.samd21.flash.select_device': self.device,
            'micros_tooling.platforms.samd21.flash.erase_programmer': 'bossac',
            'micros_tooling.platforms.samd21.flash.erase': None,
        }
        self.mocks = {}
        for name, value in patches.items():
            patcher = patch(name, return_value=value)
            self.mocks[name.rsplit('.', 1)[-1]] = patcher.start()
            self.addCleanup(patcher.stop)
        self.args = argparse.Namespace(command='erase', port='/mkr', yes=True, json=True)

    def test_removes_console_and_all_matching_enrollment_receipts_before_erasing(self):
        def erase(*args):
            self.assertEqual(self.remote.raw.call_count, 3)
            self.assertEqual(self.usb.read('enrollment.json'), {})
            self.assertEqual(self.old.read('enrollment.json'), {})
            self.assertTrue(self.other.read('enrollment.json')['flashed'])
        self.mocks['erase'].side_effect = erase
        result = er.erase(self.args)
        self.assertTrue(result['erased'])
        self.assertEqual(self.mocks['erase'].call_args.args[:2], ('/mkr', 'serial'))
        archived = Workspace(Path(result['session']) / self.usb.root.name)
        self.assertTrue(archived.read('previous-enrollment.json')['confirmed'])

    def test_samd_erase_requires_no_confirmation(self):
        self.args.yes = False
        self.args.json = False
        with patch('builtins.input', side_effect=AssertionError('unexpected confirmation')):
            self.assertTrue(er.erase(self.args)['erased'])
        self.mocks['erase'].assert_called_once()

    def test_console_failure_stops_before_erase(self):
        self.remote.raw.side_effect = [b'{"devices":[]}', TimeoutError('offline')]
        with self.assertRaises(TimeoutError):
            er.erase(self.args)
        self.mocks['erase'].assert_not_called()
        self.assertTrue(self.usb.read('enrollment.json')['confirmed'])

    def test_changed_identity_stops_before_revoke(self):
        self.mocks['read_identity'].side_effect = [(self.board['device_id'], ''), ('aabbccddeeff', '')]
        with self.assertRaisesRegex(PackageError, 'changed'):
            er.erase(self.args)
        self.assertEqual(self.remote.raw.call_count, 1)
        self.mocks['erase'].assert_not_called()

    def test_programmer_failure_does_not_report_complete(self):
        self.mocks['erase'].side_effect = PackageError('USB disconnected')
        with self.assertRaisesRegex(PackageError, 'USB disconnected'):
            er.erase(self.args)
        receipt = Workspace(self.root / 'onboarding' / self.board['device_id']).read('erase.json')
        self.assertTrue(receipt['console_removed'])
        self.assertFalse(receipt.get('complete'))

    def test_missing_programmer_does_not_revoke(self):
        self.mocks['erase_programmer'].side_effect = PackageError('missing tools')
        with self.assertRaisesRegex(PackageError, 'missing tools'):
            er.erase(self.args)
        self.remote.raw.assert_not_called()


class SamdEraseBackendTest(unittest.TestCase):
    def test_erase_tracks_bootloader_location_and_never_reads_or_writes_flash(self):
        from micros_tooling.platforms.samd21 import flash as f
        device = argparse.Namespace(device='/app', vid=0x2341, pid=0x8054, serial_number='serial', location='usb-1')
        boot = argparse.Namespace(device='/boot', vid=0x2341, pid=0x0054, serial_number=None, location='usb-1')
        other = argparse.Namespace(device='/other', vid=0x2341, pid=0x0054, serial_number=None, location='usb-2')
        remote = Mock()
        remote.request.return_value = dict(result=0)
        with patch.object(f.list_ports, 'comports', side_effect=[[device], [other, boot]]), patch.object(f, 'erase_programmer', return_value='bossac'), patch('micros_tooling.platforms.samd21.transport.SerialRemote', return_value=remote), patch('micros_tooling.terminal.progress.run') as run:
            f.erase('/app', 'serial', Path('/tmp/erase.log'))
        self.assertEqual(run.call_args.args[0], ['bossac', '-p', '/boot', '-U', 'true', '-e'])
        remote.request.assert_called_once_with('BOOTLOADER', allow_error=True)
        remote.serial.close.assert_called_once()

    def test_arduino_programmer_help_on_stderr_is_accepted(self):
        from micros_tooling.platforms.samd21 import flash as f
        with patch.object(f, 'bossac', return_value='bossac'), patch.object(f.subprocess, 'run', return_value=argparse.Namespace(returncode=1, stdout='', stderr='keep the 8KB of bootloader for SAM Dxx')):
            self.assertEqual(f.erase_programmer(), 'bossac')

    def test_incompatible_bossac_is_rejected_before_reset(self):
        from micros_tooling.platforms.samd21 import flash as f
        with patch.object(f, 'bossac', return_value='bossac'), patch.object(f.subprocess, 'run', return_value=argparse.Namespace(returncode=0, stdout='erase starting at offset', stderr='')):
            with self.assertRaisesRegex(PackageError, 'bossac 1.7.0'):
                f.erase_programmer()


if __name__ == '__main__':
    unittest.main()
