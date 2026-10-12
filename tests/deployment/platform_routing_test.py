"""Enrolled embedded boards use their own protocol without legacy pairing."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from micros_tooling.deployment.selection import resolve_enrolled_platform
from micros_tooling.storage.workspace import Workspace

class RoutingTest(unittest.TestCase):
    def test_usb_identity_mismatch_closes_without_writing(self):
        from micros_tooling.platforms.embedded.transport import verify_selected_usb
        from micros_tooling.storage.packages import PackageError
        remote = Mock()
        remote.status.return_value = dict(identity=dict(device_id='other'))
        with self.assertRaisesRegex(PackageError, 'does not match'):
            verify_selected_usb(remote, 'selected')
        remote.serial.close.assert_called_once()
        remote.request.assert_not_called()

    def test_matching_usb_identity_keeps_connection(self):
        from micros_tooling.platforms.embedded.transport import verify_selected_usb
        remote = Mock()
        remote.status.return_value = dict(identity=dict(device_id='selected'))
        self.assertIs(verify_selected_usb(remote, 'selected'), remote)
        remote.serial.close.assert_not_called()

    def test_enrollment_receipt_selects_platform_firmware_and_relay(self):
        for platform, command in ((p, c) for p in ('samd21', 'esp8266') for c in ('deploy', 'history', 'restart')):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                Workspace(root / 'onboarding' / 'usb-key').write('enrollment.json', dict(
                    confirmed=True, board=dict(device_id='ac1da4519140'), firmware='/prepared/base.elf'))
                remote = Mock()
                remote.raw.return_value = json.dumps(dict(devices=[dict(device_id='ac1da4519140', name='desk', status=dict(platform=platform))])).encode()
                args = argparse.Namespace(command=command, device='desk', platform=None, via=None, port=None)
                with patch('micros_tooling.fleet.server.configured_remote', return_value=remote), patch('micros_tooling.storage.client.operator_directory', return_value=root):
                    resolve_enrolled_platform(args)
                self.assertEqual(args.platform, platform)
                self.assertEqual(args.via, 'relay')
                self.assertEqual(args.enrolled_profile['firmware'], '/prepared/base.elf')

    def test_old_esp_enrollment_recovers_verified_binary(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); firmware=root/'base.elf';firmware.write_bytes(b'elf')
            image=root/'00010000.bin';image.write_bytes(b'bound binary')
            Workspace(root/'onboarding/board').write('enrollment.json',dict(confirmed=True,board=dict(device_id='ac1da4519140'),firmware=str(firmware),files=[dict(offset=0x10000,path=str(image),sha256=hashlib.sha256(image.read_bytes()).hexdigest())]))
            remote=Mock();remote.raw.return_value=json.dumps(dict(devices=[dict(device_id='ac1da4519140',name='desk',status=dict(platform='esp8266'))])).encode()
            args=argparse.Namespace(command='deploy',device='desk',platform=None,via=None,port=None)
            with patch('micros_tooling.fleet.server.configured_remote',return_value=remote),patch('micros_tooling.storage.client.operator_directory',return_value=root):
                resolve_enrolled_platform(args)
            self.assertEqual(firmware.with_suffix('.bin').read_bytes(), image.read_bytes())

    def test_explicit_platform_does_not_need_console(self):
        with patch('micros_tooling.fleet.server.configured_remote') as remote:
            resolve_enrolled_platform(argparse.Namespace(command='status', device=None, platform='samd21'))
        remote.assert_not_called()

    def test_esp32_keeps_existing_route(self):
        remote = Mock()
        remote.raw.return_value = json.dumps(dict(devices=[dict(device_id='ac1da4519140', name='desk', status=dict(platform='esp32'))])).encode()
        args = argparse.Namespace(command='status', device='desk', platform=None)
        with patch('micros_tooling.fleet.server.configured_remote', return_value=remote):
            resolve_enrolled_platform(args)
        self.assertIsNone(args.platform)

class BaseReceiptTest(unittest.TestCase):
    def test_update_does_not_lock_another_controllers_session(self):
        from micros_tooling.deployment.selection import record_base_update
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            other=Workspace(root/'onboarding/a-other')
            other.write('enrollment.json',dict(confirmed=True,board=dict(device_id='112233445566')))
            selected=Workspace(root/'onboarding/z-selected')
            selected.write('enrollment.json',dict(confirmed=True,board=dict(device_id='ac1da4519140'),firmware='/old.elf',base_sha256='ab'*32))
            args=argparse.Namespace(enrolled_profile=dict(device_id='ac1da4519140'))
            with other.locked(), patch('micros_tooling.storage.client.operator_directory',return_value=root):
                record_base_update(args,dict(confirmed=True,status=dict(base_sha256='cd'*32)),Path('/new.elf'))
            receipt=selected.read('enrollment.json')
            self.assertEqual(receipt['firmware'],'/new.elf')
            self.assertEqual(receipt['previous_bases'][0]['firmware'],'/old.elf')

class ExplicitTargetTest(unittest.TestCase):
    def test_explicit_target_wins_over_old_local_profile_names(self):
        from micros_tooling.platforms import handler_for
        from micros_tooling.platforms.esp8266 import cli as esp
        from micros_tooling.platforms.samd21 import cli as samd
        with patch.object(esp, 'handles', return_value=True), patch.object(samd, 'handles', return_value=True):
            self.assertIsNone(handler_for(argparse.Namespace(platform='esp32')))
            self.assertIs(handler_for(argparse.Namespace(platform='samd21')), samd.main)
            self.assertIs(handler_for(argparse.Namespace(platform='esp8266')), esp.main)

class IdempotentDeployTest(unittest.TestCase):
    def test_matching_live_graph_does_not_write_or_restart(self):
        import contextlib, io
        from micros_tooling.platforms.samd21 import cli as samd
        from micros_tooling.platforms.esp8266 import cli as esp
        for module in (samd, esp):
            with self.subTest(platform=module.__name__):
                status = dict(base_sha256='ab'*32, good_sha256='cd'*32, good=0, active=0, pending=0, services=[dict(state=4)])
                remote = Mock()
                remote.status.return_value = status
                manager = Mock()
                manager.__enter__ = Mock(return_value=remote)
                manager.__exit__ = Mock(return_value=False)
                args = argparse.Namespace(command='deploy', device=None, firmware=Path('/fake/base.elf'), json=True)
                report=dict(graph_sha256='cd'*32,base_sha256='ab'*32,bank=0,
                            plan=dict(services=[],channels=[]))
                with patch.object(module, 'connect', return_value=manager), patch.object(module, 'base_info', return_value=dict(hash=bytes.fromhex('ab'*32))), patch.object(module, 'build', return_value=report), contextlib.redirect_stdout(io.StringIO()) as output:
                    module.main(args)
                self.assertTrue(json.loads(output.getvalue())['unchanged'])
                remote.deploy.assert_not_called()
                remote.request.assert_not_called()
                remote.relay.register_release.assert_called_once()

if __name__ == '__main__': unittest.main()
