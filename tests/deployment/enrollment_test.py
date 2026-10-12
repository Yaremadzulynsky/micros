"""Enrollment must preserve identity and recovery evidence across interruptions."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from micros_tooling.deployment import enrollment as e
from micros_tooling.storage.packages import PackageError, digest
from micros_tooling.storage.workspace import Workspace

BOARD = dict(platform='esp8266', chip='ESP8266EX', device_id='f4cfa2d08ce3', flash_mb=4)


def args(**kw):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='command')
    e.add_parser(sub)
    result = p.parse_args(['enroll', '--json'])
    for k, v in kw.items():
        setattr(result, k, v)
    return result


class EnrollmentTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        root_patch = patch.object(e, 'ROOT', self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        self.operator = self.root / 'operator'
        self.operator.mkdir()
        (self.operator / 'client.json').write_text(json.dumps(dict(url='https://console.example', device_url='https://relay.example')))
        (self.operator / 'servercert.pem').write_bytes(b'certificate')
        (self.operator / 'admin.token').write_text('test-token')
        environment = patch.dict(os.environ, {'MICROS_CLIENT_DIR': str(self.operator)})
        environment.start()
        self.addCleanup(environment.stop)
        self.workspace = Workspace(self.root / 'workspace')
        self.remote = Mock()
        self.remote.raw.return_value = b'{}'

    def test_starter_binding_uses_detected_identity_and_capacity(self):
        from micros_tooling.config.scaffold import create, bind_starter
        from micros_tooling.config.configuration import read_toml, load_project
        for platform, capacity in (('esp32', 8), ('esp8266', 4), ('samd21', None)):
            root = create(self.root / ('app-' + platform), platform)
            before = (root / 'units/000000000000.toml').read_bytes()
            destination = bind_starter(root, BOARD['device_id'], platform, capacity)
            self.assertEqual(read_toml(destination)['unit']['device_id'], BOARD['device_id'])
            if platform == 'esp32':
                self.assertEqual(read_toml(destination)['board']['flash_mb'], 8)
            self.assertFalse((root / 'units/000000000000.toml').exists())
            self.assertEqual((root / 'build/enrollment/000000000000.toml.before').read_bytes(), before)
            self.assertEqual(len(load_project(destination)['services']), 1)
            self.assertEqual(bind_starter(root, BOARD['device_id'], platform, capacity), destination)

    def test_starter_binding_preserves_custom_and_mismatched_units(self):
        from micros_tooling.config.scaffold import create, bind_starter
        for change in ('custom', 'platform', 'multiple'):
            root = create(self.root / ('app-' + change))
            placeholder = root / 'units/000000000000.toml'
            if change == 'custom':
                placeholder.write_text(placeholder.read_text().replace('stack_bytes = 4096', 'stack_bytes = 8192'))
            if change == 'multiple':
                (root / 'units/aabbccddeeff.toml').write_text(placeholder.read_text().replace('000000000000', 'aabbccddeeff'))
            before = {p.name: p.read_bytes() for p in (root / 'units').glob('*.toml')}
            self.assertIsNone(bind_starter(root, BOARD['device_id'], 'esp8266' if change == 'platform' else 'esp32', 4))
            self.assertEqual({p.name: p.read_bytes() for p in (root / 'units').glob('*.toml')}, before)

    def test_project_write_failure_does_not_undo_successful_enrollment(self):
        from contextlib import nullcontext
        result = dict(online=True, device_id=BOARD['device_id'], platform='esp32', flash_mb=4, message='Board online.')
        with patch('micros_tooling.deployment.server_selection.enrollment_server', return_value=nullcontext()), \
             patch.object(e, '_enroll', return_value=result), \
             patch('micros_tooling.storage.client.application_root', return_value=self.root), \
             patch('micros_tooling.config.scaffold.bind_starter', side_effect=OSError('read-only project')):
            self.assertTrue(e.enroll(args())['online'])
        self.remote.raw.assert_not_called()

    def test_picker_offers_known_unfinished_enrollment(self):
        from micros_tooling.communication import discovery
        receipt = dict(board=BOARD, name='desk', flashed=True, base_sha256='ab' * 32)
        Workspace(self.operator / 'onboarding' / BOARD['device_id']).write('enrollment.json', receipt)
        port = argparse.Namespace(device='/test-port', vid=0x10c4, pid=1, location='1')
        discovered = dict(port=port.device, state='identified', platform='esp8266', device_id=BOARD['device_id'])
        with patch('serial.tools.list_ports.comports', return_value=[port]), \
             patch.object(e, 'interactive', return_value=True), \
             patch.object(discovery, 'discover', return_value=[discovered]), \
             patch('builtins.input', return_value='1'), patch.object(e, 'progress') as progress:
            selected = e.choose_port(args(), roster=[dict(device_id=BOARD['device_id'], name='desk')])
        self.assertEqual(selected, port.device)
        self.assertIn('resume unfinished enrollment', str(progress.call_args_list))

    def test_stopped_local_server_explains_recovery_before_usb(self):
        (self.operator / 'prvtkey.pem').write_text('private-test-key')
        self.remote.raw.side_effect = ConnectionRefusedError()
        with patch('micros_tooling.fleet.server.configured_remote', return_value=self.remote), \
             patch.object(e, 'choose_port') as choose:
            with self.assertRaisesRegex(PackageError, 'Start the selected server.*No controller was accessed'):
                e.enroll(args())
        choose.assert_not_called()

    def test_bad_controller_choice_does_not_repeat_discovery(self):
        from micros_tooling.communication import discovery
        ports = [argparse.Namespace(device='/one', vid=0x10c4, pid=1, location='1'),
                 argparse.Namespace(device='/two', vid=0x10c4, pid=1, location='2')]
        with patch('serial.tools.list_ports.comports', return_value=ports), \
             patch.object(e, 'interactive', return_value=True), \
             patch.object(discovery, 'discover', return_value=[]) as discover, \
             patch('builtins.input', side_effect=['bad', '99', '2']):
            self.assertEqual(e.choose_port(args()), '/two')
        discover.assert_called_once()

    def test_probe_versions_and_chip_families(self):
        for label in ('Chip is ESP8266EX', 'Chip type: ESP8266EX'):
            self.assertEqual(e.parse_probe(label + '\nMAC: f4:cf:a2:d0:8c:e3\nDetected flash size: 4MB'), BOARD)
        self.assertEqual(e.parse_probe('Chip is ESP32-D0WD-V3\nMAC: aa:bb:cc:dd:ee:ff\nDetected flash size: 8MB')['platform'], 'esp32')
        self.assertEqual(e.parse_probe('Chip is ESP32-PICO-V3-02\nMAC: aa:bb:cc:dd:ee:ff\nDetected flash size: 8MB')['platform'], 'esp32')
        for chip in ('ESP32-S3', 'ESP32-C3', 'ESP32-C6', 'ESP32-S2'):
            with self.assertRaisesRegex(PackageError, 'only has bases'):
                e.parse_probe(f'Chip is {chip}\nMAC: aa:bb:cc:dd:ee:ff\nDetected flash size: 4MB')
        with self.assertRaisesRegex(PackageError, 'not a supported'):
            e.parse_probe('Chip is ESP8266EX\nMAC: aa:bb:cc:dd:ee:ff\nDetected flash size: 2MB')

    def test_aliases_deduplicated_but_identical_serials_not_merged(self):
        def port(device, location):
            return argparse.Namespace(device=device, location=location, vid=0x10c4, pid=0xea60, serial_number='0001', description='CP2102')
        ports = [port('/dev/cu.SLAB', '1'), port('/dev/cu.usbserial', '1')]
        with patch('serial.tools.list_ports.comports', return_value=ports):
            self.assertEqual(e.choose_port(args()), '/dev/cu.usbserial')
            ports.append(port('/dev/cu.second', '2'))
            with self.assertRaisesRegex(PackageError, 'Several boards'):
                e.choose_port(args())

    def test_changed_device_or_flash_rejected(self):
        for change in (dict(device_id='aabbccddeeff'), dict(flash_mb=8), dict(platform='esp32')):
            with self.assertRaises(PackageError):
                e.check_identity(BOARD, dict(BOARD, **change))

    def test_enrollment_retry_preserves_exact_token(self):
        self.remote.raw.side_effect = [TimeoutError('reply lost'), b'{}']
        with self.assertRaises(TimeoutError):
            e.credentials(self.operator, self.workspace, self.remote, BOARD, 'desk', [])
        directory = self.operator / 'enrollments' / BOARD['device_id']
        token = (directory / 'relay.token').read_bytes()
        e.credentials(self.operator, self.workspace, self.remote, BOARD, 'desk', [])
        self.assertEqual(token, (directory / 'relay.token').read_bytes())
        self.assertEqual(self.remote.raw.call_args_list[0], self.remote.raw.call_args_list[1])
        self.assertEqual((directory / 'relay.token').stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads((directory / 'server.json').read_text())['url'], 'https://relay.example')

    def test_existing_enrollment_without_token_is_not_rotated(self):
        with patch.object(e, 'ROOT', self.root), self.assertRaisesRegex(PackageError, 'will not be reset'):
            e.credentials(self.operator, self.workspace, self.remote, BOARD, 'desk', [dict(device_id=BOARD['device_id'])])
        self.remote.raw.assert_not_called()

    def test_wrong_server_certificate_refused(self):
        saved = self.root / 'saved'
        saved.mkdir()
        (saved / 'relay.token').write_text('ab' * 32)
        (saved / 'relay-ca.pem').write_bytes(b'another server')
        with self.assertRaisesRegex(PackageError, 'another server'):
            e.credentials(self.operator, self.workspace, self.remote, BOARD, 'desk', [], saved)
        self.remote.raw.assert_not_called()

    def prepared(self):
        firmware = self.root / 'base.elf'
        firmware.write_bytes(b'elf')
        image = self.root / 'image.bin'
        image.write_bytes(b'image')
        return dict(firmware=str(firmware), base_sha256=digest(b'elf'),
                    files=[dict(offset=0x10000, path=str(image), sha256=digest(b'image'))],
                    flash_args=[])

    def test_prepare_installs_missing_esp8266_tools_before_build(self):
        session = self.root / 'new-session'
        calls = []
        def run(command, *a, **kw):
            calls.append(command)
            if '--output' in command:
                base = Path(command[command.index('--output') + 1])
                for relative in ('micros_esp8266.elf', 'micros_esp8266.bin',
                                 'bootloader/bootloader.bin', 'partition_table/partition-table.bin'):
                    path = base / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b'prepared image')
        with patch.object(e, 'run_tool', side_effect=run), patch('micros_tooling.platforms.esp8266.firmware.bind'):
            result = e.prepare(BOARD, args(), session, self.root)
        self.assertIn('micros_tooling.platforms.esp8266.bootstrap', calls[0])
        self.assertIn('--output', calls[1])
        self.assertEqual(calls[1][calls[1].index('--relay-ca') + 1], str(self.root / 'relay-ca.pem'))
        self.assertEqual(len(result['files']), 4)

    def test_esp32_readiness_requires_pinned_checkout_and_activation(self):
        from micros_tooling.platforms.esp32 import bootstrap
        sdk = self.root / 'idf'
        with patch.object(bootstrap, 'SDK', sdk):
            self.assertFalse(bootstrap.ready())
            sdk.mkdir()
            (sdk / 'export.sh').touch()
            with patch.object(bootstrap.subprocess, 'check_output', return_value='wrong revision'), \
                 patch.object(bootstrap.subprocess, 'run') as activate:
                self.assertFalse(bootstrap.ready())
                activate.assert_not_called()
            with patch.object(bootstrap.subprocess, 'check_output', return_value=bootstrap.SDK_REVISION), \
                 patch.object(bootstrap.subprocess, 'run') as activate:
                activate.return_value.returncode = 1
                self.assertFalse(bootstrap.ready())
                activate.return_value.returncode = 0
                self.assertTrue(bootstrap.ready())

    def test_usb_probe_prefers_current_sdk_esptool(self):
        with patch('importlib.util.find_spec', return_value=object()), \
             patch.object(e.shutil, 'which', return_value='/unrelated/esptool'):
            self.assertEqual(e.esptool(), [sys.executable, '-m', 'esptool'])

    def test_interrupted_success_is_verified_without_second_write(self):
        receipt = self.prepared()
        receipt['flash_started'] = True
        with patch.object(e, 'probe', return_value=BOARD), patch.object(e, 'esptool', return_value=['esptool']), patch.object(e, 'run_tool') as tool:
            e.install(BOARD, 'port', self.root, receipt, Mock())
        self.assertIn('verify_flash', tool.call_args.args[0])
        self.assertEqual(tool.call_count, 1)
        self.assertTrue(receipt['flashed'])

    def test_uncertain_flash_is_never_blindly_repeated(self):
        receipt = self.prepared()
        receipt['flash_started'] = True
        with patch.object(e, 'probe', return_value=BOARD), patch.object(e, 'esptool', return_value=['esptool']), patch.object(e, 'run_tool', side_effect=PackageError('mismatch')) as tool:
            with self.assertRaisesRegex(PackageError, '--retry-flash'):
                e.install(BOARD, 'port', self.root, receipt, Mock())
        self.assertEqual(tool.call_count, 1)
        self.assertNotIn('write_flash', tool.call_args.args[0])

    def test_changed_image_or_elf_prevents_writes(self):
        for path in ('image.bin', 'base.elf'):
            receipt = self.prepared()
            (self.root / path).write_bytes(b'corrupt')
            with patch.object(e, 'probe', return_value=BOARD), patch.object(e, 'esptool', return_value=['esptool']), patch.object(e, 'run_tool') as tool:
                with self.assertRaises(PackageError):
                    e.install(BOARD, 'port', self.root, receipt, Mock())
                tool.assert_not_called()

    def test_flash_attempt_is_saved_before_write(self):
        receipt = self.prepared()
        saved = []
        def write(*a, **kw):
            self.assertTrue(saved[-1]['flash_started'])
            raise TimeoutError('interrupted')
        with patch.object(e, 'probe', return_value=BOARD), patch.object(e, 'esptool', return_value=['esptool']), patch.object(e, 'run_tool', side_effect=write):
            with self.assertRaises(TimeoutError):
                e.install(BOARD, 'port', self.root, receipt, lambda: saved.append(dict(receipt)))
        self.assertNotIn('flashed', receipt)

    def test_enroll_after_erase_uses_fresh_artifacts(self):
        session = self.operator / 'onboarding' / BOARD['device_id']
        state = Workspace(session)
        state.write('enrollment.json', {})
        state.write('erase.json', dict(console_removed=True, complete=True))
        old_backup = session / 'before-flash.bin'
        old_backup.write_bytes(b'historical recovery data')
        self.remote.raw.return_value = b'{"devices":[]}'
        prepared = dict(base_sha256='ab' * 32, files=[{}])
        with patch.object(e, 'choose_port', return_value='port'), patch.object(e, 'probe', return_value=BOARD), \
             patch('micros_tooling.storage.client.operator_directory', return_value=self.operator), \
             patch('micros_tooling.fleet.server.configured_remote', return_value=self.remote), \
             patch.object(e, 'credentials', return_value=self.root), patch.object(e, 'prepare', return_value=prepared) as prepare, \
             patch.object(e, 'install') as install, patch.object(e, 'connect_wifi'), patch.object(e, 'verify_console'):
            e.enroll(args(name='desk'))
        fresh = prepare.call_args.args[2]
        self.assertEqual(fresh.parent, (session / 'reenrollments').resolve())
        self.assertEqual(install.call_args.args[2], fresh)
        self.assertEqual(state.read('enrollment.json')['work_session'], str(fresh))
        self.assertEqual(old_backup.read_bytes(), b'historical recovery data')

    def test_already_enrolled_device_is_rejected(self):
        receipt = dict(board=BOARD, name='desk', confirmed=True, flashed=True, files=[{}], base_sha256='ab' * 32)
        session = self.operator / 'onboarding' / BOARD['device_id']
        Workspace(session).write('enrollment.json', receipt)
        self.remote.raw.return_value = json.dumps(dict(devices=[dict(device_id=BOARD['device_id'], name='desk')])).encode()
        with patch.object(e, 'choose_port', return_value='port'), patch.object(e, 'probe', return_value=BOARD), \
             patch('micros_tooling.storage.client.operator_directory', return_value=self.operator), \
             patch('micros_tooling.fleet.server.configured_remote', return_value=self.remote), \
             patch.object(e, 'credentials', return_value=self.root), patch.object(e, 'prepare') as prepare, \
             patch.object(e, 'install') as install, patch.object(e, 'connect_wifi') as wifi, patch.object(e, 'verify_console') as verify:
            with self.assertRaisesRegex(PackageError, 'already enrolled'):
                e.enroll(args(port='port'))
        prepare.assert_not_called()
        install.assert_not_called()
        wifi.assert_not_called()
        verify.assert_not_called()

    def test_connected_unfinished_enrollment_resumes_without_reflashing(self):
        session = self.operator / 'onboarding' / BOARD['device_id']
        receipt = dict(board=BOARD, name='desk', flashed=True, files=[{}], base_sha256='ab' * 32)
        Workspace(session).write('enrollment.json', receipt)
        existing = dict(device_id=BOARD['device_id'], name='desk', online=True,
                        status=dict(identity=dict(base_sha256='ab' * 32)))
        self.remote.raw.return_value = json.dumps(dict(devices=[existing])).encode()
        with patch.object(e, 'choose_port', return_value='port'), patch.object(e, 'probe', return_value=BOARD), \
             patch('micros_tooling.fleet.server.configured_remote', return_value=self.remote), \
             patch.object(e, 'credentials', return_value=self.root), \
             patch.object(e, 'prepare') as prepare, patch.object(e, 'install') as install, \
             patch.object(e, 'connect_wifi'), patch.object(e, 'verify_console'):
            result = e.enroll(args())
        self.assertTrue(result['online'])
        prepare.assert_not_called()
        install.assert_not_called()
        self.assertTrue(Workspace(session).read('enrollment.json')['confirmed'])

    def test_resume_requires_same_board_name_and_base(self):
        existing = dict(device_id=BOARD['device_id'], name='desk',
                        status=dict(identity=dict(base_sha256='ab' * 32)))
        receipt = dict(board=BOARD, name='desk', flashed=True, base_sha256='ab' * 32)
        self.assertTrue(e.resumable(receipt, existing))
        for change in (dict(confirmed=True), dict(flashed=False), dict(name='other'),
                       dict(base_sha256='cd' * 32), dict(base_sha256=None),
                       dict(board=dict(BOARD, device_id='aabbccddeeff'))):
            with self.subTest(change=change):
                self.assertFalse(e.resumable(dict(receipt, **change), existing))

    def test_wifi_failure_resumes_without_reflashing_or_rotating(self):
        self.remote.raw.return_value = b'{"devices":[]}'
        def installed(board, port, session, receipt, save, **kw):
            receipt['flashed'] = True
            save()
        with patch.object(e, 'choose_port', return_value='port'), patch.object(e, 'probe', return_value=BOARD), \
             patch('micros_tooling.storage.client.operator_directory', return_value=self.operator), \
             patch('micros_tooling.fleet.server.configured_remote', return_value=self.remote), \
             patch.object(e, 'prepare', return_value=dict(files=[{}], base_sha256='ab' * 32)) as prepare, \
             patch.object(e, 'install', side_effect=installed) as install, \
             patch.object(e, 'connect_wifi', side_effect=[PackageError('Wi-Fi unavailable'), None]), \
             patch.object(e, 'verify_console') as verify:
            with self.assertRaisesRegex(PackageError, 'Wi-Fi unavailable'):
                e.enroll(args(name='desk'))
            saved_token = (self.operator / 'enrollments' / BOARD['device_id'] / 'relay.token').read_bytes()
            result = e.enroll(args(name='desk'))
            self.assertTrue(result['online'])
            self.assertEqual(saved_token, (self.operator / 'enrollments' / BOARD['device_id'] / 'relay.token').read_bytes())
        prepare.assert_called_once()
        install.assert_called_once()
        verify.assert_called_once()

    def test_reused_base_never_needs_build_tools_or_flash(self):
        self.remote.raw.return_value = json.dumps(dict(devices=[dict(device_id=BOARD['device_id'], name='desk')])).encode()
        with patch.object(e, 'choose_port', return_value='port'), patch.object(e, 'probe', return_value=BOARD), \
             patch('micros_tooling.storage.client.operator_directory', return_value=self.operator), \
             patch('micros_tooling.fleet.server.configured_remote', return_value=self.remote), \
             patch.object(e, 'installed_base', return_value='ab' * 32), \
             patch.object(e, 'credentials', return_value=self.root), patch.object(e, 'prepare') as prepare, \
             patch.object(e, 'install') as install, patch.object(e, 'connect_wifi'), patch.object(e, 'verify_console'):
            with self.assertRaisesRegex(PackageError, 'already enrolled'):
                e.enroll(args())
        prepare.assert_not_called()
        install.assert_not_called()

    def test_rebuild_failed_enrollment_preserves_token_and_previous_evidence(self):
        self.remote.raw.return_value = b'{"devices":[]}'
        def installed(board, port, session, receipt, save, **kw):
            receipt['flashed'] = True
            save()
        session = self.operator / 'onboarding' / BOARD['device_id']
        state = Workspace(session)
        with patch.object(e, 'choose_port', return_value='port'), patch.object(e, 'probe', return_value=BOARD), \
             patch('micros_tooling.fleet.server.configured_remote', return_value=self.remote), \
             patch.object(e, 'prepare', side_effect=[dict(files=[{}], base_sha256='ab' * 32),
                                                   dict(files=[{}], base_sha256='cd' * 32)]) as prepare, \
             patch.object(e, 'install', side_effect=installed) as install, \
             patch.object(e, 'connect_wifi', side_effect=[PackageError('invalid RPC frame'), None]), \
             patch.object(e, 'verify_console'):
            with self.assertRaisesRegex(PackageError, 'invalid RPC frame'):
                e.enroll(args(name='desk'))
            old = state.read('enrollment.json')
            artifact = session / 'previous-build-evidence'
            artifact.write_bytes(b'preserved')
            token = self.operator / 'enrollments' / BOARD['device_id'] / 'relay.token'
            saved_token = token.read_bytes()
            result = e.enroll(args(rebuild_base=True))
        self.assertTrue(result['online'])
        self.assertEqual(result['base_sha256'], 'cd' * 32)
        self.assertEqual(token.read_bytes(), saved_token)
        self.assertEqual(artifact.read_bytes(), b'preserved')
        archives = list((session / 'enrollment-history').glob('*.json'))
        self.assertEqual(len(archives), 1)
        self.assertEqual(json.loads(archives[0].read_text()), old)
        self.assertEqual(prepare.call_count, 2)
        self.assertEqual(install.call_count, 2)
        self.assertEqual(prepare.call_args.args[2].parent, (session / 'rebuilds').resolve())

    def test_rebuild_rejects_confirmed_receipt_without_replacing_it(self):
        self.remote.raw.return_value = b'{"devices":[]}'
        state = Workspace(self.operator / 'onboarding' / BOARD['device_id'])
        receipt = dict(board=BOARD, name='desk', confirmed=True, flashed=True)
        state.write('enrollment.json', receipt)
        with patch.object(e, 'choose_port', return_value='port'), patch.object(e, 'probe', return_value=BOARD), \
             patch('micros_tooling.fleet.server.configured_remote', return_value=self.remote), \
             patch.object(e, 'prepare') as prepare, patch.object(e, 'install') as install:
            with self.assertRaisesRegex(PackageError, 'unfinished enrollment'):
                e.enroll(args(rebuild_base=True))
        self.assertEqual(state.read('enrollment.json'), receipt)
        self.assertFalse((state.root / 'enrollment-history').exists())
        prepare.assert_not_called()
        install.assert_not_called()

    def test_rebuild_conflicts_fail_before_server_or_usb_access(self):
        for option in (dict(detect=True), dict(retry_flash=True), dict(firmware=Path('/unused'))):
            with patch('micros_tooling.fleet.server.configured_remote') as remote, patch.object(e, 'choose_port') as usb:
                with self.assertRaisesRegex(PackageError, 'without --firmware'):
                    e.enroll(args(rebuild_base=True, **option))
                remote.assert_not_called()
                usb.assert_not_called()

    def test_offline_roster_never_counts_as_confirmation(self):
        self.remote.raw.return_value = json.dumps(dict(devices=[dict(device_id=BOARD['device_id'], online=False)])).encode()
        with self.assertRaisesRegex(PackageError, 'has not confirmed'):
            e.verify_console(self.remote, BOARD, 'ab' * 32, timeout=0)
        self.remote.status.assert_not_called()

    def test_existing_base_requires_matching_physical_and_saved_identity(self):
        identity = dict(device_id=BOARD['device_id'], base_sha256='ab' * 32)
        existing = dict(status=dict(identity=identity))
        with patch('micros_tooling.platforms.esp8266.transport.SerialRemote') as serial:
            serial.return_value.__enter__.return_value.status.return_value = dict(identity=identity)
            self.assertEqual(e.installed_base(BOARD, 'port', self.remote, existing), 'ab' * 32)
            serial.return_value.__enter__.return_value.status.return_value = dict(identity=dict(identity, device_id='aabbccddeeff'))
            self.assertIsNone(e.installed_base(BOARD, 'port', self.remote, existing))

    def test_install_does_not_read_or_require_backup(self):
        receipt = self.prepared()
        receipt['backup_sha256'] = 'obsolete legacy backup hash'
        partial = self.root / 'before-flash.partial'
        partial.write_bytes(b'incomplete historical backup')
        with patch.object(e, 'probe', return_value=BOARD), patch.object(e, 'esptool', return_value=['esptool']), patch.object(e, 'run_tool') as tool:
            e.install(BOARD, 'port', self.root, receipt, Mock())
        self.assertEqual(tool.call_count, 1)
        self.assertIn('write_flash', tool.call_args.args[0])
        self.assertNotIn('read_flash', tool.call_args.args[0])
        self.assertFalse((self.root / 'before-flash.bin').exists())
        self.assertEqual(partial.read_bytes(), b'incomplete historical backup')

    def test_usb_secret_command_failure_does_not_expose_token(self):
        relay = self.root / 'relay'
        relay.mkdir()
        token = 'ab' * 32
        (relay / 'relay.token').write_text(token)
        (relay / 'server.json').write_text('{"url":"https://relay.example"}')
        with patch('micros_tooling.platforms.esp8266.transport.SerialRemote') as serial:
            device = serial.return_value.__enter__.return_value
            device.status.return_value = dict(identity=dict(device_id=BOARD['device_id']), base_sha256='cd' * 32, network=dict(relay_configured=False))
            device.request.side_effect = ValueError('bad reply ' + token)
            with self.assertRaises(PackageError) as failure:
                e.connect_wifi(BOARD, 'port', args(), dict(base_sha256='cd' * 32), relay)
            self.assertNotIn(token, str(failure.exception))

    def test_console_wrong_identity_rejected(self):
        board = dict(BOARD, platform='esp32')
        self.remote.raw.return_value = json.dumps(dict(devices=[dict(device_id=board['device_id'], online=True)])).encode()
        self.remote.status.return_value = dict(identity=dict(device_id=board['device_id'], base_sha256='cd' * 32))
        with self.assertRaisesRegex(PackageError, 'different board or base'):
            e.verify_console(self.remote, board, 'ab' * 32)


    def test_esp8266_verification_uses_standard_status_and_retries_gateway(self):
        from micros_tooling.communication.remote import RemoteRejected
        status = dict(identity=dict(device_id=BOARD['device_id'], base_sha256='ab' * 32))
        self.remote.raw.return_value = json.dumps(dict(devices=[dict(device_id=BOARD['device_id'], online=True)])).encode()
        self.remote.status.side_effect = [RemoteRejected(504, b'error code: 504'), status]
        with patch.object(e.time, 'sleep'):
            self.assertEqual(e.verify_console(self.remote, BOARD, 'ab' * 32), status)
        self.assertEqual(self.remote.status.call_count, 2)
        self.remote.request.assert_not_called()

    def test_gateway_retry_is_bounded_and_actionable(self):
        from micros_tooling.communication.remote import RemoteRejected
        self.remote.raw.side_effect = RemoteRejected(503, b'busy')
        with self.assertRaisesRegex(PackageError, 'Rerun micros enroll'):
            e.verify_console(self.remote, BOARD, 'ab' * 32, timeout=0)
        self.assertEqual(self.remote.raw.call_count, 1)

    def test_authentication_errors_are_not_retried(self):
        from micros_tooling.communication.remote import RemoteRejected
        self.remote.raw.side_effect = RemoteRejected(401, b'unauthorized')
        with patch.object(e.time, 'sleep') as sleep, self.assertRaises(RemoteRejected):
            e.verify_console(self.remote, BOARD, 'ab' * 32)
        sleep.assert_not_called()

    def test_confirmed_relay_provisioning_is_not_repeated(self):
        relay = self.root / 'relay'
        relay.mkdir()
        (relay / 'relay.token').write_text('ab' * 32)
        (relay / 'server.json').write_text('{"url":"https://relay.example"}')
        receipt = dict(base_sha256='cd' * 32, relay_provisioned=True)
        status = dict(identity=dict(device_id=BOARD['device_id']), base_sha256='cd' * 32,
                      network=dict(relay_configured=True, connected=True))
        with patch('micros_tooling.platforms.esp8266.transport.SerialRemote') as serial:
            device = serial.return_value.__enter__.return_value
            device.status.return_value = status
            e.connect_wifi(BOARD, 'port', args(), receipt, relay)
            device.request.assert_not_called()

    def test_no_saved_wifi_prompts_without_waiting(self):
        relay = self.root / 'relay'
        relay.mkdir()
        (relay / 'relay.token').write_text('ab' * 32)
        (relay / 'server.json').write_text('{"url":"https://relay.example"}')
        receipt = dict(base_sha256='cd' * 32, relay_provisioned=True)
        def status(connected):
            return dict(identity=dict(device_id=BOARD['device_id']), base_sha256='cd' * 32,
                        network=dict(relay_configured=True, configured=connected, connected=connected))
        with patch('micros_tooling.platforms.esp8266.transport.SerialRemote') as serial, \
             patch.object(e, 'wifi_secret', return_value=(b'network', b'password')) as prompt, \
             patch.object(e.time, 'sleep') as sleep:
            device = serial.return_value.__enter__.return_value
            device.status.side_effect = [status(False), status(True)]
            device.request.return_value = dict(result=0)
            e.connect_wifi(BOARD, 'port', args(), receipt, relay)
        prompt.assert_called_once()
        sleep.assert_not_called()

    def test_saved_wifi_gets_time_to_reconnect(self):
        relay = self.root / 'relay'
        relay.mkdir()
        (relay / 'relay.token').write_text('ab' * 32)
        (relay / 'server.json').write_text('{"url":"https://relay.example"}')
        receipt = dict(base_sha256='cd' * 32, relay_provisioned=True)
        def status(connected):
            return dict(identity=dict(device_id=BOARD['device_id']), base_sha256='cd' * 32,
                        network=dict(relay_configured=True, configured=True, connected=connected))
        with patch('micros_tooling.platforms.esp8266.transport.SerialRemote') as serial, \
             patch.object(e, 'wifi_secret') as prompt, patch.object(e.time, 'sleep') as sleep:
            device = serial.return_value.__enter__.return_value
            device.status.side_effect = [status(False), status(True), status(True)]
            e.connect_wifi(BOARD, 'port', args(), receipt, relay)
        prompt.assert_not_called()
        sleep.assert_called_once_with(1)

    def test_cancel_removes_pending_dashboard_entry(self):
        receipt = dict(pending_enrollment=True)
        save = Mock()
        self.remote.raw.side_effect = [b'{}', b'{"devices":[]}']
        result = e.cancel_enrollment(self.remote, BOARD, receipt, save)
        self.assertEqual(result, 'Enrollment canceled. Removed from the dashboard.')
        self.assertTrue(receipt['canceled'])
        save.assert_called_once()
        self.assertEqual(self.remote.raw.call_args_list[0].args[1], '/v1/revoke')

    def test_cancel_preserves_confirmed_and_unowned_enrollments(self):
        for receipt in (dict(confirmed=True, pending_enrollment=True), dict(pending_enrollment=False)):
            self.assertEqual(e.cancel_enrollment(self.remote, BOARD, receipt, Mock()), 'Enrollment canceled.')
        self.remote.raw.assert_not_called()

    def test_cancel_reports_cleanup_failure(self):
        self.remote.raw.side_effect = TimeoutError()
        receipt = dict(pending_enrollment=True)
        message = e.cancel_enrollment(self.remote, BOARD, receipt, Mock())
        self.assertIn('could not be confirmed', message)
        self.assertNotIn('canceled', receipt)

    def test_cancel_during_wifi_cleans_up_resumed_enrollment(self):
        session = self.operator / 'onboarding' / BOARD['device_id']
        Workspace(session).write('enrollment.json', dict(board=BOARD, name='desk', flashed=True, base_sha256='ab'*32))
        self.remote.raw.side_effect = [b'{"devices":[]}', b'{}', b'{"devices":[]}']
        with patch.object(e, 'choose_port', return_value='port'), patch.object(e, 'probe', return_value=BOARD), \
             patch('micros_tooling.storage.client.operator_directory', return_value=self.operator), \
             patch('micros_tooling.fleet.server.configured_remote', return_value=self.remote), \
             patch.object(e, 'credentials', return_value=self.root), patch.object(e, 'connect_wifi', side_effect=KeyboardInterrupt):
            with self.assertRaisesRegex(e.EnrollmentCancelled, 'Removed from the dashboard'):
                e.enroll(args())
        receipt = Workspace(session).read('enrollment.json')
        self.assertTrue(receipt['canceled'])
        self.assertTrue(receipt['flashed'])

    def test_password_file_is_bounded(self):
        p = self.root / 'password'
        p.write_bytes(b'x' * 1000)
        with self.assertRaises(PackageError):
            e.wifi_secret(args(ssid='network', password_file=p))
        p.write_bytes(b'password\r\n')
        self.assertEqual(e.wifi_secret(args(ssid='network', password_file=p)), (b'network', b'password'))

    def test_wifi_prompt_preserves_spaces_and_retries_invalid_inputs(self):
        with patch('sys.stdin.isatty', return_value=True), \
             patch('builtins.input', side_effect=['', ' network ']), \
             patch('getpass.getpass', side_effect=['short', ' password ']), \
             patch.object(e, 'progress') as messages:
            result = e.wifi_secret(args(json=False))
        self.assertEqual(result, (b' network ', b' password '))
        self.assertNotIn('short', str(messages.call_args_list))
        self.assertNotIn(' password ', str(messages.call_args_list))

    def test_resume_hint_selects_exact_server_and_port_without_wifi_secrets(self):
        import shlex
        receipt = dict(name='My board', flashed=True)
        hint = e.resume_hint(self.root / 'my server', '/dev/selected', receipt)
        self.assertIn('resuming will keep it', hint)
        self.assertEqual(shlex.split(hint.split('Resume: ')[1]),
                         ['env', 'MICROS_CLIENT_DIR=' + str(self.root / 'my server'),
                          'micros', 'enroll', 'My board', '--port', '/dev/selected'])
        self.assertIn('checked before another write', e.resume_hint(self.root, '/dev/selected',
                      dict(name='My board', flash_started=True)))

    def test_management_only_esp32_preparation_uses_real_declarations(self):
        from micros_tooling.config.configuration import load_project
        from micros_tooling.storage.packages import identifier
        board = dict(BOARD, platform='esp32', device_id='24dcc3c13b04')
        # Only substitute the compiler; validate the actual generated recipe.
        def onboard(workspace, options, progress):
            identifier(options.name, 'device name')
            recipe = load_project(options.project)
            self.assertEqual(recipe['services'], [])
            self.assertEqual(recipe['board']['gpio'], [])
            base = workspace.root / 'onboarding' / options.name / 'base'
            base.mkdir(parents=True)
            (base / 'micros_runtime.elf').write_bytes(b'elf')
            (base / 'app.bin').write_bytes(b'app')
            (base / 'flasher_args.json').write_text(json.dumps(dict(flash_files={'0x10000': 'app.bin'})))
        export = self.root / 'build/toolchains/esp-idf-v5.5.2/export.sh'
        export.parent.mkdir(parents=True)
        export.touch()
        for available in (True, False):
            with self.subTest(available=available), \
                 patch('micros_tooling.platforms.esp32.bootstrap.ready', return_value=available), \
                 patch.object(e, 'run_tool') as install, \
                 patch('micros_tooling.deployment.onboarding.onboard', side_effect=onboard):
                prepared = e.prepare(board, args(), self.root / str(available), self.root)
            self.assertEqual(prepared['base_sha256'], digest(b'elf'))
            if available:
                install.assert_not_called()
            else:
                self.assertIn('micros_tooling.platforms.esp32.bootstrap', install.call_args.args[0])
                self.assertEqual(install.call_args.args[1], self.root / str(available) / 'setup.log')

    def test_esp32_setup_failure_prevents_building_and_flashing(self):
        board = dict(BOARD, platform='esp32')
        with patch('micros_tooling.platforms.esp32.bootstrap.ready', return_value=False), \
             patch.object(e, 'run_tool', side_effect=PackageError('download failed; see setup.log')), \
             patch('micros_tooling.deployment.onboarding.onboard') as onboard:
            with self.assertRaisesRegex(PackageError, 'download failed'):
                e.prepare(board, args(), self.root, self.root)
        onboard.assert_not_called()


if __name__ == '__main__':
    unittest.main()
