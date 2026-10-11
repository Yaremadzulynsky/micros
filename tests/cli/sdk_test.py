"""Offline resolver and dispatcher regressions; never execute project URLs."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from micros_tooling import cli, sdk
TEST_REVISION = "a" * 40


class SDKTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.env = patch.dict(os.environ, {'MICROS_SDK_CACHE': str(self.root / 'cache')})
        self.env.start()
        self.override = os.environ.pop('MICROS_SDK', None)
        self.offline = os.environ.pop('MICROS_OFFLINE', None)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def fake_git(self, path, *args):
        if args[0] == 'checkout':
            for name in sdk.REQUIRED:
                target = path / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
        return TEST_REVISION if args[0] == 'rev-parse' else ''

    def test_download_reuse_offline(self):
        with patch.object(sdk, 'git', side_effect=self.fake_git) as git:
            result = sdk.resolve(TEST_REVISION)
            self.assertTrue((result / '.micros-cache.json').exists())
            fetches = sum(c.args[1] == 'fetch' for c in git.call_args_list)
            self.assertEqual(sdk.resolve(TEST_REVISION, offline=True), result)
            self.assertEqual(fetches, 1)
            self.assertEqual(sum(c.args[1] == 'fetch' for c in git.call_args_list), 1)

    def test_failed_download_atomic_and_retry(self):
        with patch.object(sdk, 'git', side_effect=ValueError('connection interrupted')):
            with self.assertRaisesRegex(ValueError, 'interrupted'):
                sdk.resolve(TEST_REVISION)
        self.assertFalse((self.root / 'cache' / TEST_REVISION).exists())
        self.assertFalse(list((self.root / 'cache').glob('*.partial-*')))
        with patch.object(sdk, 'git', side_effect=self.fake_git):
            self.assertTrue(sdk.resolve(TEST_REVISION).exists())

    def test_wrong_download_revision_is_never_published(self):
        def wrong(path, *args):
            return 'b'*40 if args[0] == 'rev-parse' else self.fake_git(path, *args)
        with patch.object(sdk, 'git', side_effect=wrong):
            with self.assertRaisesRegex(ValueError, 'differs'):
                sdk.resolve(TEST_REVISION)
        self.assertFalse((self.root / 'cache' / TEST_REVISION).exists())

    def test_dirty_and_incomplete_cache(self):
        with patch.object(sdk, 'git', side_effect=self.fake_git):
            target = sdk.resolve(TEST_REVISION)
        def dirty(path, *args):
            return ' M tools/micros.py' if args[0] == 'status' else self.fake_git(path, *args)
        with patch.object(sdk, 'git', side_effect=dirty):
            with self.assertRaisesRegex(ValueError, 'tracked files'):
                sdk.resolve(TEST_REVISION)
        (target / '.micros-cache.json').unlink()
        with patch.object(sdk, 'git', side_effect=self.fake_git):
            with self.assertRaisesRegex(ValueError, 'Invalid SDK cache'):
                sdk.resolve(TEST_REVISION)

    def test_offline_miss(self):
        with patch.object(sdk, 'git') as git:
            with self.assertRaisesRegex(ValueError, 'not cached'):
                sdk.resolve(TEST_REVISION, offline=True)
            git.assert_not_called()

    def test_corrupt_cache_is_preserved(self):
        target = self.root / 'cache' / TEST_REVISION
        target.mkdir(parents=True)
        (target / 'evidence').write_text('preserve')
        with patch.object(sdk, 'git', side_effect=self.fake_git):
            with self.assertRaisesRegex(ValueError, 'Move this directory aside'):
                sdk.resolve(TEST_REVISION)
        self.assertEqual((target / 'evidence').read_text(), 'preserve')

    def test_revision_and_origin_rejected_before_fetch(self):
        for value in ('main', '../escape', 'a'*39, None):
            with self.assertRaises(ValueError):
                sdk.revision(value)
        (self.root / 'micros.lock').write_text('format=1\n[sdk]\nrepository="https://evil.invalid/repo"\nrevision="' + TEST_REVISION + '"\n')
        with self.assertRaisesRegex(ValueError, 'official'):
            sdk.project_revision(self.root)

    def test_project_pin_and_ancestor(self):
        (self.root / 'micros.lock').write_text('format=1\n[sdk]\nrepository="' + sdk.OFFICIAL_REPOSITORY + '"\nrevision="' + 'a'*40 + '"\n')
        child = self.root / 'services/example'
        child.mkdir(parents=True)
        self.assertEqual(sdk.project_root(child), self.root)
        self.assertEqual(sdk.project_revision(self.root), 'a'*40)

    def test_override_mismatch(self):
        with patch.dict(os.environ, MICROS_SDK=str(self.root)), patch.object(sdk, 'git', return_value='b'*40):
            with self.assertRaisesRegex(ValueError, 'differs'):
                sdk.resolve('a'*40)

    def test_help_needs_no_sdk(self):
        with patch.object(sdk, 'resolve') as resolve, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.run(['--help']), 0)
            resolve.assert_not_called()

    def test_arguments_and_exit_code_across_sdk_handoff(self):
        with patch.object(sdk, 'check_dependencies'), patch.object(cli, 'select_sdk', return_value=self.root), patch.object(cli, 'source_checkout', return_value=None), patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 7)) as run:
            self.assertEqual(cli.run(['compose', '--json']), 7)
            self.assertEqual(run.call_args.args[0], [sys.executable, '-m', 'micros_tooling.cli', 'compose', '--json'])
            self.assertEqual(run.call_args.kwargs['env']['MICROS_SDK'], str(self.root))
            self.assertEqual(run.call_args.kwargs['env']['PYTHONPATH'], str(self.root / 'src'))
            self.assertFalse((self.root / 'build').exists())

    def test_concurrent_population(self):
        import multiprocessing
        import time
        count = self.root / 'fetches'
        def populate():
            def fake(path, *args):
                if args[0] == 'fetch':
                    with count.open('a') as stream:
                        stream.write('fetch\n')
                    time.sleep(0.05)
                return self.fake_git(path, *args)
            with patch.object(sdk, 'git', side_effect=fake):
                sdk.resolve(TEST_REVISION)
        processes = [multiprocessing.get_context('fork').Process(target=populate) for _ in range(2)]
        for process in processes:
            process.start()
        for process in processes:
            process.join(10)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(count.read_text(), 'fetch\n')

    def test_dependency_mismatch(self):
        (self.root / 'tools').mkdir()
        (self.root / 'tools/requirements-dev.txt').write_text('protobuf==0.0.1\n')
        with self.assertRaisesRegex(ValueError, 'compatible Micros CLI'):
            sdk.check_dependencies(self.root)

    def test_git_rejects_project_config_transport(self):
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
            sdk.git(self.root, 'fetch', '--depth=1', sdk.OFFICIAL_REPOSITORY, TEST_REVISION)
            command = run.call_args.args[0]
            self.assertIn('protocol.allow=never', command)
            self.assertIn('http.followRedirects=false', command)
            self.assertEqual(run.call_args.kwargs['env']['GIT_CONFIG_GLOBAL'], os.devnull)

    def test_error_and_interrupt(self):
        with patch.object(cli, 'run', side_effect=ValueError('bad lock')), patch.object(cli.sys, 'argv', ['micros', 'compose', '--json']), contextlib.redirect_stderr(io.StringIO()) as out:
            self.assertEqual(cli.entrypoint(), 1)
            self.assertEqual(json.loads(out.getvalue())['error']['message'], 'bad lock')
        with patch.object(cli, 'run', side_effect=KeyboardInterrupt), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.entrypoint(), 130)


if __name__ == '__main__':
    unittest.main()
