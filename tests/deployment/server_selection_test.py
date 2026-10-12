"""Server selection must precede authentication and remain isolated per project."""
import argparse
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from micros_tooling.storage import client
from micros_tooling.deployment import enrollment as e
from micros_tooling.deployment import server_selection as selection
from micros_tooling.fleet.server import server_main
from micros_tooling.storage.workspace import Workspace


class ServerSelectionTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        environment = {k: v for k, v in os.environ.items() if not k.startswith('MICROS_')}
        environment.update(XDG_CONFIG_HOME=str(self.root / 'config'),
                           MICROS_APPLICATION_ROOT=str(self.root / 'app'))
        stack.enter_context(patch.dict(os.environ, environment, clear=True))
        self.project = self.root / 'app'
        self.project.mkdir()
        self.workspace = Workspace(self.root / 'cache')
        stack.enter_context(patch.object(e, 'progress'))
        self.auth = stack.enter_context(patch('micros_tooling.fleet.server.configured_remote'))
        self.usb = stack.enter_context(patch.object(e, 'choose_port'))

    def profile(self, name, access=False):
        path = client.profile_directory(name)
        path.mkdir(parents=True)
        (path / 'client.json').write_text(json.dumps(dict(url=f'https://{name}.example', cloudflare_access=access)))
        (path / 'servercert.pem').write_text('test-certificate-' + name)
        (path / 'admin.token').write_text('private-test-token')
        return path

    def args(self, **kwargs):
        return argparse.Namespace(detect=False, server=None, json=True, **kwargs)

    def test_two_projects_select_independently_without_copying_credentials(self):
        lab, home = self.profile('lab'), self.profile('home')
        other = self.root / 'other'
        client.select_server('lab', project=self.project)
        client.select_server('home', project=other)
        self.assertEqual(client.operator_directory(project=self.project), lab)
        self.assertEqual(client.operator_directory(project=other), home)
        self.assertEqual([p.name for p in (self.project / '.micros').iterdir()], ['server.json'])
        self.assertNotIn('private-test-token', client.selection_file().read_text())

    def test_names_cannot_escape_configuration_directory(self):
        for name in ('../escape', '/tmp/server', 'Bad Name', '', 'x' * 49):
            with self.assertRaises(ValueError):
                client.profile_directory(name)

    def test_missing_selected_server_never_falls_back(self):
        lab = self.profile('lab')
        self.profile('default')
        client.select_server('lab')
        (lab / 'client.json').unlink()
        self.assertEqual(client.operator_directory(), lab)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            with selection.enrollment_server(self.args()):
                self.fail('Must not continue')

    def test_headless_without_selection_does_not_use_legacy_cloudflare(self):
        self.profile('default', access=True)
        with self.assertRaisesRegex(ValueError, 'Choose a server first'):
            e.enroll(self.args())
        self.auth.assert_not_called()
        self.usb.assert_not_called()

    def test_picker_selects_before_auth_and_updates_cache_restoring_environment(self):
        self.profile('default', access=True)
        lab = self.profile('lab')
        old_cache = client.application_cache(self.project)
        os.environ['MICROS_STATE_DIR'] = str(old_cache)
        with patch.object(e, 'interactive', return_value=True), patch('builtins.input', return_value='2'):
            with selection.enrollment_server(self.args()):
                self.assertEqual(client.operator_directory(), lab)
                self.assertNotEqual(Path(os.environ['MICROS_STATE_DIR']), old_cache)
                self.auth.assert_not_called()
                self.usb.assert_not_called()
        self.assertNotIn('MICROS_CLIENT_DIR', os.environ)
        self.assertEqual(os.environ['MICROS_STATE_DIR'], str(old_cache))
        self.assertEqual(client.operator_directory(), lab)

    def test_explicit_environment_skips_picker_and_preserves_custom_cache(self):
        lab = self.profile('lab')
        os.environ.update(MICROS_CLIENT_DIR=str(lab), MICROS_STATE_DIR=str(self.root / 'custom'))
        with patch('builtins.input') as prompt:
            with selection.enrollment_server(self.args()):
                self.assertEqual(os.environ['MICROS_STATE_DIR'], str(self.root / 'custom'))
        prompt.assert_not_called()
        self.assertEqual(os.environ['MICROS_CLIENT_DIR'], str(lab))

    def test_detect_bypasses_server_selection(self):
        args = self.args()
        args.detect = True
        with patch.object(client, 'operator_directory', side_effect=AssertionError('No server access')):
            with selection.enrollment_server(args):
                pass
        self.auth.assert_not_called()

    def test_cancel_does_not_authenticate_or_touch_board(self):
        self.profile('default', access=True)
        with patch.object(e, 'interactive', return_value=True), patch('builtins.input', return_value='q'):
            with self.assertRaises(e.EnrollmentCancelled):
                e.enroll(self.args())
        self.auth.assert_not_called()
        self.usb.assert_not_called()

    def test_connect_imports_only_operator_bundle(self):
        source = self.profile('source')
        (source / 'prvtkey.pem').write_text('server-only-private-key')
        with patch('builtins.input', side_effect=['a', 'lab', str(source)]), patch('sys.stdout', new_callable=io.StringIO):
            chosen = selection.choose_server(self.workspace)
        self.assertEqual(chosen, client.profile_directory('lab'))
        self.assertEqual({p.name for p in chosen.iterdir()}, {'client.json', 'servercert.pem', 'admin.token'})
        self.assertTrue((source / 'prvtkey.pem').exists())

    def test_create_can_defer_start_without_docker_or_enrollment(self):
        def setup(argv):
            self.assertEqual(argv, ['--profile', 'lab', 'setup', '--host', '192.0.2.1'])
            self.profile('lab')
        with patch('builtins.input', side_effect=['n', 'lab', '192.0.2.1', 'n']), \
             patch('micros_tooling.fleet.server.server_main', side_effect=setup) as command:
            with self.assertRaisesRegex(e.EnrollmentCancelled, 'Server saved'):
                selection.choose_server(self.workspace)
        command.assert_called_once()
        self.auth.assert_not_called()
        self.usb.assert_not_called()

    def test_flag_selects_profile_without_prompt(self):
        lab = self.profile('lab')
        args = self.args()
        args.server = 'lab'
        with patch('builtins.input') as prompt:
            with selection.enrollment_server(args):
                self.assertEqual(client.operator_directory(), lab)
        prompt.assert_not_called()

    def test_server_use_selects_named_compose_project_on_shutdown(self):
        self.profile('lab')
        with patch('sys.stdout', new_callable=io.StringIO):
            server_main(['use', 'lab'])
        with patch('micros_tooling.fleet.server.RelayRemote'), \
             patch('micros_tooling.fleet.server.subprocess.run') as run:
            server_main(['shutdown'])
        argv = run.call_args.args[0]
        self.assertEqual(argv[argv.index('-p') + 1], 'micros-server-lab')
        self.assertEqual(run.call_args.kwargs['env']['MICROS_SERVER_STATE'], str(client.profile_directory('lab')))

    def test_broken_profile_does_not_hide_usable_servers(self):
        broken = self.profile('broken')
        (broken / 'client.json').write_text('{"url": 123}')
        self.profile('lab')
        profiles = client.saved_servers()
        self.assertIn('error', profiles[0])
        self.assertEqual(profiles[1]['url'], 'https://lab.example')

    def test_legacy_selection_remains_listed_after_cache_changes(self):
        source = self.profile('lab')
        legacy = self.workspace.root / 'server'
        legacy.parent.mkdir(parents=True)
        source.rename(legacy)
        client.select_server('legacy', directory=legacy)
        profiles = client.saved_servers(Workspace(self.root / 'new-cache'))
        self.assertEqual([(p['name'], p['directory']) for p in profiles], [('legacy', str(legacy))])

    def test_enrollment_failure_restores_environment(self):
        self.profile('lab')
        args = self.args()
        args.server = 'lab'
        with self.assertRaisesRegex(RuntimeError, 'failed'):
            with selection.enrollment_server(args):
                raise RuntimeError('failed')
        self.assertNotIn('MICROS_CLIENT_DIR', os.environ)
        self.assertNotIn('MICROS_STATE_DIR', os.environ)

    def test_new_local_server_is_started_only_after_confirmation(self):
        def command(argv):
            if argv[2] == 'setup':
                self.profile('lab')
        with patch('builtins.input', side_effect=['n', 'lab', '192.0.2.1', 'y']), \
             patch('micros_tooling.fleet.server.server_main', side_effect=command) as run:
            self.assertEqual(selection.choose_server(self.workspace), client.profile_directory('lab'))
        self.assertEqual(run.call_args_list[1].args[0], ['--profile', 'lab', 'start'])

    def test_explicit_flag_cannot_silently_override_environment(self):
        self.profile('lab')
        os.environ['MICROS_SERVER'] = 'lab'
        args = self.args()
        args.server = 'other'
        with self.assertRaisesRegex(ValueError, 'Unset MICROS_CLIENT_DIR and MICROS_SERVER'):
            with selection.enrollment_server(args):
                self.fail('Conflicting selection')


if __name__ == '__main__':
    unittest.main()
