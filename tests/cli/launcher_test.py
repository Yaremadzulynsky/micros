"""All shipped entrypoints share project selection, flags and SDK validation."""
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from micros_tooling.config.scaffold import bind_starter


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='micros launcher ')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('MICROS_')}
        self.env.update(PYTHONPATH=str(ROOT / 'src'), MICROS_OFFLINE='1',
                        MICROS_CLIENT_DIR=str(self.directory / 'client'),
                        MICROS_SDK_CACHE=str(self.directory / 'cache'))
        self.app = self.directory / 'my application'
        self.invoke([str(ROOT / 'micros')], ['new', str(self.app)], self.directory)
        self.routes = [[str(ROOT / 'micros')], [str(self.app / 'micros')],
                       [sys.executable, '-m', 'micros_tooling.cli']]
        installed = ROOT / 'build/python/bin/micros'
        if installed.exists():
            self.routes.append([str(installed)])

    def invoke(self, route, args, cwd, code=0):
        result = subprocess.run([*route, *args], cwd=cwd, env=self.env,
                                capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def test_project_selection_and_generation_from_nested_directory(self):
        bind_starter(self.app, 'aabbccddeeff', 'esp32', 4)
        nested = self.app / 'services/climate-sensor/src'
        for args in (['compose', '--json'], ['generate', '--json']):
            results = [json.loads(self.invoke(route, args, nested).stdout) for route in self.routes]
            self.assertTrue(all(result == results[0] for result in results))
        self.assertTrue((self.app / 'build/services/climate-sensor/generated/climate_ipc.c').exists())
        self.assertEqual((self.app / '.sdk').resolve(), ROOT.resolve())

    def test_target_starters_share_parser_and_scaffold(self):
        for index, route in enumerate(self.routes):
            for platform in ('esp32', 'samd21', 'esp8266'):
                app = self.directory / f'{platform}-{index}'
                self.invoke(route, ['new', str(app), '--platform', platform], self.app)
                self.assertEqual(sorted(p.name for p in (app / 'units').glob('*.toml')), ['host.toml'])
                bind_starter(app, 'aabbccddeeff', platform, 4 if platform != 'samd21' else None)
                result = self.invoke([str(app / 'micros')], ['compose', '--json'], self.directory)
                self.assertEqual(json.loads(result.stdout)['services'][0]['name'], 'example.climate-sensor')
                self.assertEqual((app / 'micros').read_bytes(), (self.app / 'micros').read_bytes())

    def test_help_explicit_project_and_sdk_escape_do_not_recurse(self):
        bind_starter(self.app, 'aabbccddeeff', 'esp32', 4)
        for args in (['--help'], ['build', '--help'], ['sdk', '--help'], ['host', '--help'], ['setup', '--help']):
            results = [self.invoke(route, args, self.app).stdout for route in self.routes]
            self.assertTrue(all(value == results[0] for value in results), args)
        for route in self.routes:
            self.invoke(route, ['generate', '--project', str(self.app / 'units/aabbccddeeff.toml'), '--json'], self.app)

    def test_pin_mismatch_and_usage_are_structured_and_fail(self):
        for route in self.routes:
            result = self.invoke(route, ['new', '--wrong', '--json'], self.app, code=2)
            self.assertEqual(json.loads(result.stderr)['error']['code'], 'usage')
            generated = self.invoke(route, ['generate', '--wrong', '--json'], self.app, code=2)
            self.assertEqual(json.loads(generated.stderr)['error']['code'], 'usage')
        lock = self.app / 'micros.lock'
        revision = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
        lock.write_text(lock.read_text().replace(revision, '0' * 40))
        for route in self.routes:
            result = self.invoke(route, ['compose', '--json'], self.app, code=1)
            self.assertIn('SDK revision differs', json.loads(result.stderr)['error']['message'])
        self.assertFalse((self.directory / 'cache').exists())

    def test_standalone_install_and_cached_sdk_without_virtualenv(self):
        # A non-editable package has no firmware checkout beside its modules.
        installed = self.directory / 'installed'
        shutil.copytree(ROOT / 'src/micros_tooling', installed / 'micros_tooling',
                        ignore=shutil.ignore_patterns('__pycache__'))
        binary = self.directory / 'bin/micros'
        binary.parent.mkdir()
        binary.write_text('#!' + sys.executable + '\nfrom micros_tooling.cli import entrypoint\nraise SystemExit(entrypoint())\n')
        binary.chmod(0o755)
        candidate = self.directory / 'cache-candidate'
        candidate.mkdir()
        for name in ('src', 'config', 'tools/templates', 'examples/hello-service'):
            shutil.copytree(ROOT / name, candidate / name,
                            ignore=shutil.ignore_patterns('__pycache__', '*.egg-info', 'generated'))
        for name in ('micros', 'tools/requirements-dev.txt'):
            shutil.copy2(ROOT / name, candidate / name)
        def git(*args):
            return subprocess.check_output(['git', '-C', str(candidate), *args], text=True).strip()
        git('init', '--quiet')
        git('add', '.')
        git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
            '-c', 'core.hooksPath=/dev/null', 'commit', '--quiet', '-m', 'SDK fixture')
        revision = git('rev-parse', 'HEAD')
        cache = self.directory / 'cache' / revision
        cache.parent.mkdir()
        candidate.rename(cache)
        (cache / '.micros-cache.json').write_text(json.dumps(dict(revision=revision,
            repository='https://github.com/Yaremadzulynsky/micros.git')))
        self.env.update(PYTHONPATH=str(installed), PATH=str(binary.parent) + os.pathsep + self.env.get('PATH', ''),
                        MICROS_SDK=str(cache))
        app = self.directory / 'cached app'
        self.invoke([str(binary)], ['new', str(app), '--platform', 'samd21'], self.directory)
        self.env.pop('MICROS_SDK')
        # Both entrypoints work without mutating a cached SDK to create an interpreter shim.
        for route in ([str(binary)], [str(app / 'micros')]):
            self.invoke(route, ['generate', '--json'], app)
        self.invoke([str(binary)], ['new', str(self.directory / 'second app'), '--platform', 'esp8266'], app)
        (app / '.sdk').unlink()
        self.invoke([str(app / 'micros')], ['generate', '--json'], app)
        self.assertFalse((cache / 'build/python').exists())

    def test_starter_lifecycle_and_existing_destination(self):
        self.assertEqual(sorted(p.name for p in (self.app / 'units').glob('*.toml')), ['host.toml'])
        for route in self.routes:
            self.invoke(route, ['compose', '-d', 'host'], self.app)
            self.invoke(route, ['compose'], self.app)
            for command in ('pins', 'deploy'):
                result = self.invoke(route, [command], self.app, code=1)
                self.assertIn('Run ./micros enroll', result.stderr)
        self.invoke(self.routes[0], ['test'], self.app)
        source = self.app / 'services/climate-sensor/src/service.c'
        original = source.read_bytes()
        self.invoke(self.routes[0], ['new', str(self.app)], self.app, code=1)
        self.assertEqual(source.read_bytes(), original)

    def test_new_service_examples_and_filtered_tests_through_launchers(self):
        for index, route in enumerate(self.routes):
            directory = self.app / 'services' / f'counter-{index}'
            result = self.invoke(route, ['scaffold-service', str(directory), '--example', 'counter', '--json'], self.app)
            files = json.loads(result.stdout)['files']
            self.assertEqual(len(files), 3)
            before = (directory / 'src/service.c').read_bytes()
            self.invoke(route, ['scaffold-service', str(directory), '--new'], self.app, code=1)
            self.assertEqual((directory / 'src/service.c').read_bytes(), before)
            self.invoke(route, ['generate', '--service', str(directory), '--json'], self.app)
        result = self.invoke(self.routes[0], ['test', '-v', '-k', 'settings'], self.app)
        self.assertIn('Ran 1 test', result.stderr)
        for command in ('compose', 'pins', 'test'):
            self.invoke(self.routes[0], [command, '--help'], self.app)


if __name__ == '__main__':
    unittest.main()
