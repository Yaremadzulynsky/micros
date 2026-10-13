"""Ensure board selection cannot silently target another unit."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from micros_tooling.config import application as project
from micros_tooling.config.repository import ROOT


class UnitSelectionTest(unittest.TestCase):
    def test_host_is_local_and_does_not_change_board_selection(self):
        import contextlib
        import io
        from micros_tooling.config.scaffold import create, bind_starter
        with tempfile.TemporaryDirectory() as temporary:
            root = create(Path(temporary) / 'application')
            def compose(*args):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    project.main(['compose', '--json', *args], root, Mock())
                return json.loads(output.getvalue())
            with patch('micros_tooling.fleet.server.configured_remote') as server:
                self.assertIsNone(compose()['board'])
                first = bind_starter(root, 'aabbccddeeff', 'esp32', 4)
                self.assertEqual(project.select_unit(root=root), first)
                self.assertIsNotNone(compose()['board'])
                self.assertIsNone(compose('-d', 'host')['board'])
                bind_starter(root, 'aabbccddee00', 'esp8266', 4)
                self.assertIsNone(compose('-d', 'host')['board'])
                with self.assertRaisesRegex(ValueError, 'Select -d'):
                    compose()
                for command in ('pins', 'build', 'deploy', 'plan'):
                    with self.assertRaisesRegex(ValueError, 'host is local'):
                        project.main([command, '-d', 'host'], root, Mock())
                server.assert_not_called()

    def test_explicit_selection_with_multiple_boards(self):
        directory = ROOT / 'build/tests'
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            root = Path(temporary)
            (root / 'units').mkdir()
            state = root / 'state'
            state.mkdir()
            for identity in ('e89f6d30e1a8', 'b0a732c8082c'):
                (root / 'units' / (identity + '.toml')).write_text(
                    '[unit]\ndevice_id = "' + identity + '"\n[board]\nprofile = "test"\n')
            (state / 'devices.json').write_text(json.dumps({'devices': {
                'feather': {'device_id': 'e89f6d30e1a8'}}}))
            with self.assertRaisesRegex(ValueError, 'Select -d'):
                project.select_unit(root=root, state=state)
            remote = Mock()
            remote.raw.return_value = json.dumps({'devices': [dict(
                name='feather', device_id='e89f6d30e1a8', online=False, last_seen=0)]}).encode()
            with patch('micros_tooling.fleet.server.configured_remote', return_value=remote):
                with self.assertRaisesRegex(ValueError, 'unknown or ambiguous'):
                    project.select_unit('unknown', root=root, state=state)
                self.assertEqual(project.select_unit('feather', root=root, state=state).stem, 'e89f6d30e1a8')
            with patch('micros_tooling.fleet.server.configured_remote', return_value=None):
                with self.assertRaisesRegex(ValueError, 'Server connection required'):
                    project.select_unit('feather', root=root, state=state)
            self.assertEqual(project.select_unit('b0a732c8082c', root=root, state=state).stem, 'b0a732c8082c')
            with patch('micros_tooling.fleet.server.configured_remote') as server:
                self.assertEqual(project.select_unit('B0A732C8082C', root=root, state=state).stem, 'b0a732c8082c')
                with self.assertRaisesRegex(ValueError, 'units/111111111111.toml'):
                    project.select_unit('111111111111', root=root, state=state)
                server.assert_not_called()


class ApplicationCommandsTest(unittest.TestCase):
    def invoke(self, args):
        with patch.dict('os.environ', {'MICROS_SDK': str(ROOT)}), \
             patch.object(project.subprocess, 'call', return_value=0) as call, \
             patch.object(Path, 'is_dir', return_value=True), \
             patch.object(project, 'select_unit', return_value=Path('/application/units/unit.toml')), \
             patch.object(project, 'unit_identity', return_value='e89f6d30e1a8'):
            dispatch = Mock(return_value=0)
            result = project.main(args, Path('/application'), dispatch)
            return result, (call.call_args or dispatch.call_args).args[0]

    def test_deploy_routes_only_selected_unit_and_preserves_dry_run(self):
        _, command = self.invoke(['deploy', '-d', 'feather', '--dry-run'])
        self.assertEqual(command, ['deploy', '--project',
                                  '/application/units/unit.toml', '--dry-run',
                                  '-d', 'e89f6d30e1a8'])

    def test_explicit_project_and_sdk_passthrough_are_preserved(self):
        for args in (['generate', '--project', '/tmp/unit.toml'], ['sdk', 'devices']):
            with self.subTest(args=args):
                _, command = self.invoke(args)
                self.assertEqual(command, [*(args[1:] if args[0] == 'sdk' else args)])

    def test_plan_routes_only_selected_unit_and_preserves_json(self):
        _, command = self.invoke(['plan', '-d', 'feather', '--json'])
        self.assertEqual(command, ['plan', '--project',
                                  '/application/units/unit.toml', '--json',
                                  '-d', 'e89f6d30e1a8'])

    def test_test_discovery_remains_application_local(self):
        _, command = self.invoke(['test'])
        self.assertEqual(command, [project.sys.executable, '-m', 'unittest', 'discover',
                                  '-s', '/application/tests', '-p', '*_test.py'])

    def test_test_filters_are_passed_without_shell_interpretation(self):
        _, command = self.invoke(['test', '-v', '-f', '-k', 'counter', '-k', '*timer*', '-p', '*_test.py'])
        self.assertEqual(command[-6:], ['-v', '-f', '-k', 'counter', '-k', '*timer*'])

    def test_local_help_does_not_select_or_contact_a_board(self):
        import contextlib
        import io
        for command in ('compose', 'pins', 'test'):
            with patch.object(project, 'select_unit') as select, \
                 patch.object(project.subprocess, 'call') as run, \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as exit:
                    project.main([command, '--help'], Path('/application'), Mock())
                self.assertEqual(exit.exception.code, 0)
                self.assertIn('micros ' + command, output.getvalue())
                select.assert_not_called()
                run.assert_not_called()

    def test_missing_test_directory_has_guidance(self):
        with tempfile.TemporaryDirectory() as root, patch.object(project.subprocess, 'call') as run:
            with self.assertRaisesRegex(ValueError, 'Add application tests'):
                project.main(['test'], root, Mock())
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
