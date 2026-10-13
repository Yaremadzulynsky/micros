"""Complete unit recipes and hardware-bound deployment selection."""
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
from micros_tooling.config.configuration import load_project, select_unit
from micros_tooling.config.resources import select_board, load_board
from micros_tooling.storage.packages import PackageError


class UnitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.unit = self.directory / 'aabbccddeeff.toml'
        self.unit.write_text('[unit]\ndevice_id = "aabbccddeeff"\n[board]\nprofile = "esp32"\nflash_mb = 4\n[board.gpio]\n[services.hello]\nmemory = { arena = "RAM" }\nsource = "."\nname = "example.hello"\nversion = "1.0.0"\n[services.hello.build]\nsources = ["service.c"]\n[services.hello.capabilities]\ntimers = 1\ngpio = []\n')

    def test_selects_normalized_hardware_identity(self):
        self.assertEqual(select_unit(self.directory, 'AA:BB:CC:DD:EE:FF'), self.unit)
        recipe = load_project(self.unit)
        self.assertEqual(recipe['board']['gpio'], [])
        self.assertEqual([s['name'] for s in recipe['services']], ['example.hello'])
        self.assertEqual(recipe['services'][0]['sources'], [str(self.directory / 'service.c')])
        self.assertEqual(select_board(self.unit), self.unit)

    def test_missing_unit_never_falls_back(self):
        with self.assertRaisesRegex(PackageError, 'Unit configuration missing'):
            select_unit(self.directory, '112233445566')

    def test_explicit_project_cannot_target_another_unit(self):
        with self.assertRaisesRegex(PackageError, 'does not match'):
            select_unit(self.directory, '112233445566', self.unit)

    def test_filename_must_match_identity(self):
        wrong = self.directory / '112233445566.toml'
        wrong.write_bytes(self.unit.read_bytes())
        with self.assertRaisesRegex(PackageError, 'filename must match'):
            load_project(wrong)

    def test_generic_project_cannot_bypass_unit_selection(self):
        generic = self.directory / 'micros.toml'
        generic.write_text('[services]\n')
        with self.assertRaisesRegex(PackageError, 'does not match'):
            select_unit(self.directory, 'aabbccddeeff', generic)

    def test_unit_must_own_its_board(self):
        self.unit.write_text('[unit]\ndevice_id="aabbccddeeff"\n[services]\n')
        with self.assertRaisesRegex(PackageError, 'own \\[board\\]'):
            load_project(self.unit)

    def test_board_override_cannot_change_hardware(self):
        board = self.directory / 'board.toml'
        board.write_text('[board]\nprofile="esp32"\nflash_mb=8\n')
        with self.assertRaisesRegex(PackageError, 'override differs'):
            select_board(self.unit, board)

    def test_board_snapshot_can_be_used_in_base_preparation(self):
        snapshot = self.directory / 'board.toml'
        snapshot.write_bytes(self.unit.read_bytes())
        self.assertEqual(load_board(snapshot), load_board(self.unit))
        self.assertEqual(load_project(self.unit, board=snapshot)['board']['flash_mb'], 4)

    def test_missing_live_identity_rejects_selection(self):
        with self.assertRaisesRegex(PackageError, 'no hardware identity'):
            select_unit(self.directory, None, self.unit)

    def test_network_deploy_checks_live_identity_before_build(self):
        from micros_tooling import dispatch as micros
        from micros_tooling.storage.packages import digest
        firmware = self.directory / 'base.elf'
        firmware.write_bytes(b'paired-base')
        workspace = MagicMock()
        workspace.root = self.directory
        workspace.device.return_value = ('unit', dict(device_id='aabbccddeeff',
                                                       firmware_sha256=digest(firmware.read_bytes())))
        workspace.files.return_value = (None, None, firmware)
        remote = MagicMock()
        remote.status.return_value = {'identity': {'device_id': '112233445566'}}
        with patch.object(sys, 'argv', ['micros', 'deploy', '-d', 'unit', '--project', str(self.unit)]),\
                patch.object(micros, 'Workspace', return_value=workspace),\
                patch('micros_tooling.fleet.server.discover_for_command', return_value=None),\
                patch('micros_tooling.fleet.server.configured_remote', return_value=None),\
                patch('micros_tooling.deployment.diagnostics.connect', return_value=(None, None, remote)),\
                patch.object(micros, 'build_application') as build:
            with self.assertRaisesRegex(PackageError, 'does not match'):
                micros.main()
            build.assert_not_called()
            remote.request.assert_not_called()

    def test_network_deploy_checks_base_before_build(self):
        from micros_tooling import dispatch as micros
        from micros_tooling.storage.packages import digest
        firmware = self.directory / 'base.elf'
        firmware.write_bytes(b'paired-base')
        workspace = MagicMock()
        workspace.root = self.directory
        workspace.device.return_value = ('unit', dict(device_id='aabbccddeeff',
                                                       firmware_sha256=digest(firmware.read_bytes())))
        workspace.files.return_value = (None, None, firmware)
        remote = MagicMock()
        remote.status.return_value = {'identity': dict(device_id='aabbccddeeff', base_sha256='0' * 64, abi_major=0, abi_revision=7, graph_format=1)}
        with patch.object(sys, 'argv', ['micros', 'deploy', '-d', 'unit', '--project', str(self.unit)]),\
                patch.object(micros, 'Workspace', return_value=workspace),\
                patch('micros_tooling.fleet.server.discover_for_command', return_value=None),\
                patch('micros_tooling.fleet.server.configured_remote', return_value=None),\
                patch('micros_tooling.deployment.diagnostics.connect', return_value=(None, None, remote)),\
                patch.object(micros, 'build_application') as build:
            with self.assertRaisesRegex(PackageError, 'Paired base does not match'):
                micros.main()
            build.assert_not_called()
            remote.request.assert_not_called()

    def test_arena_placement_is_required_and_strict(self):
        original = self.unit.read_text()
        for replacement in ('', 'memory = { arena = "auto" }\n'):
            self.unit.write_text(original.replace('memory = { arena = "RAM" }\n', replacement))
            with self.assertRaisesRegex(PackageError, 'memory.arena must explicitly'):
                load_project(self.unit)

    def test_psram_requires_hardware_profile(self):
        self.unit.write_text(self.unit.read_text().replace('arena = "RAM"', 'arena = "PSRAM"'))
        with self.assertRaisesRegex(PackageError, 'selected board has no PSRAM'):
            load_project(self.unit)
        self.unit.write_text(self.unit.read_text().replace('profile = "esp32"', 'profile = "adafruit_feather_esp32_v2"'))
        self.assertEqual(load_project(self.unit)['services'][0]['arena'], 'PSRAM')

    def test_fixture_units_have_distinct_services_and_hardware(self):
        feather = load_project(ROOT / 'tests/fixtures/composition/units/aabbccdd0001.toml')
        plain = load_project(ROOT / 'tests/fixtures/composition/units/aabbccdd0002.toml')
        self.assertEqual([g['pin'] for g in plain['board']['gpio']], [27])
        self.assertEqual(plain['board']['flash_mb'], 4)
        self.assertEqual(feather['board'].get('flash_mb', 8), 8)
        self.assertNotIn('board.button', [s['name'] for s in plain['services']])
        for recipe in (plain, feather):
            for service in recipe['services']:
                self.assertTrue(all(Path(source).is_file() for source in service['sources']))


if __name__ == '__main__':
    unittest.main()
