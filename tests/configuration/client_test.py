"""Client authentication migration and disposable server-specific caches."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from micros_tooling.storage.client import import_operator, operator_directory, application_cache
from micros_tooling.storage.workspace import Workspace


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {'MICROS_CLIENT_DIR': str(self.root / 'operator')})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_import_copies_only_operator_files_and_preserves_source(self):
        source = self.root / 'legacy/server'
        source.mkdir(parents=True)
        for name in ('client.json', 'servercert.pem', 'admin.token', 'prvtkey.pem', 'registry.sqlite'):
            (source / name).write_text(name)
        destination = import_operator(source)
        self.assertEqual({p.name for p in destination.iterdir()}, {'client.json', 'servercert.pem', 'admin.token'})
        self.assertEqual(len(list(source.iterdir())), 5)
        self.assertEqual(import_operator(source), destination)
        (source / 'admin.token').write_text('different')
        with self.assertRaisesRegex(ValueError, 'configuration differs'):
            import_operator(source)
        self.assertEqual((destination / 'admin.token').read_text(), 'admin.token')

    def test_cache_is_separate_from_credentials_and_changes_with_server(self):
        directory = operator_directory()
        directory.mkdir()
        config = directory / 'client.json'
        config.write_text('{"url":"https://one.example"}')
        first = application_cache(self.root / 'app')
        config.write_text('{"url":"https://two.example"}')
        second = application_cache(self.root / 'app')
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_relative_to(self.root / 'app/build'))
        self.assertFalse(first.is_relative_to(directory))

    def test_fresh_workspace_uses_user_operator_configuration(self):
        self.assertEqual(operator_directory(Workspace(self.root / 'empty')), self.root / 'operator')

    def test_build_fetches_server_base_without_local_pairing(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from micros_tooling import dispatch as micros
        from micros_tooling.fleet.server import RelayRemote
        identity = '0123456789ab'
        unit = self.root / (identity + '.toml')
        unit.write_text('[unit]\ndevice_id = "' + identity + '"\n[board]\nprofile = "test"\n')
        workspace = Workspace(self.root / 'fresh-cache')
        remote = MagicMock(spec=RelayRemote)
        remote.host = 'server.example'
        remote.device_id = identity
        remote.raw.return_value = ('{"devices":[{"device_id":"' + identity + '","name":"desk","online":true,"last_seen":0}]}').encode()
        remote.status.return_value = {'identity': {'device_id': identity, 'base_sha256': 'a' * 64}}
        firmware = self.root / 'downloaded/firmware.elf'
        with patch.object(sys, 'argv', ['micros', 'build', '-d', 'desk', '--project', str(unit)]), \
             patch.object(micros, 'Workspace', return_value=workspace), \
             patch('micros_tooling.fleet.server.configured_remote', return_value=remote), \
             patch('micros_tooling.storage.artifacts.fetch_base', return_value=firmware) as fetch, \
             patch('micros_tooling.storage.artifacts.sync_releases') as sync, \
             patch('micros_tooling.config.resources.select_board', return_value=None), \
             patch.object(micros, 'build_application', return_value=[]) as build, \
             patch('micros_tooling.platforms.esp32.device.prepare', return_value=(None, None, {})):
            micros.main()
        fetch.assert_called_once_with(remote, workspace, remote.status.return_value)
        sync.assert_called_once_with(remote, workspace, identity)
        self.assertEqual(build.call_args.args[1], firmware)
        self.assertFalse((workspace.root / 'devices' / identity / 'firmware.elf').exists())
        remote.request.assert_not_called()
