"""Exercise a generated external application's real managed host lifecycle."""
import json
import io
from contextlib import redirect_stdout
from unittest.mock import patch
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
from micros_tooling.config.scaffold import create

RUNTIME = Path(sys.argv.pop(1)).resolve() if len(sys.argv) > 1 else ROOT/'build/host/micros-control'


class ExternalHostTests(unittest.TestCase):
    def test_controller_startup_failure_is_visible(self):
        from micros_tooling.host import daemon, cli
        from micros_tooling.storage.store import Store
        with tempfile.TemporaryDirectory(prefix='micros startup failure ') as temporary:
            store = Store(temporary)
            error = PermissionError(1, 'Operation not permitted')
            with patch.object(daemon, 'socket_path', return_value=store.root/'controller.sock'), \
                 patch.object(daemon.socket, 'socket') as socket_factory:
                server = socket_factory.return_value.__enter__.return_value
                server.bind.side_effect = error
                with self.assertRaises(PermissionError):
                    daemon.serve(store.root, RUNTIME)
                self.assertEqual(server.bind.call_count, 1)
            self.assertFalse(daemon.running(store))
            output = io.StringIO()
            with redirect_stdout(output):
                cli.main(['status', '--store', temporary])
            state = json.loads(output.getvalue())
            self.assertEqual(state['controller']['state'], 'stopped')
            self.assertIn('Operation not permitted', state['controller']['startup_error'])
            self.assertIsNone(state['last_failure'])
            self.assertIsNone(state['last_good'])
            for diagnostic in (None, 'controller bind failed: Operation not permitted'):
                if diagnostic is not None:
                    (store.root/'controller.log').write_text(diagnostic)
                output = io.StringIO()
                with redirect_stdout(output):
                    cli.main(['logs', '--store', temporary])
                self.assertIn('Controller diagnostic', output.getvalue())
                self.assertIn('Operation not permitted', output.getvalue())
            (store.root/'runtime.log').write_text('service output')
            output = io.StringIO()
            with redirect_stdout(output):
                cli.main(['logs', '--store', temporary])
            self.assertEqual(output.getvalue().strip(), 'service output')

    def test_counter_commands_are_packaged(self):
        from micros_tooling.host.build import build
        from micros_tooling.storage.packages import read_package, admission_plan
        with tempfile.TemporaryDirectory(prefix='micros counter ') as temporary:
            app = Path(temporary)
            shutil.copytree(ROOT/'examples/typed-commands', app/'counter')
            project = app/'host.toml'
            project.write_text('[services.counter]\nsource="counter"\ncontract="service.toml"\n'
                               'memory={arena="RAM",stack_bytes=2048}\n'
                               'expose_commands=["get_value", "set_value"]\n')
            packages = [read_package(p.read_bytes()) for p in build(project, app/'build/host', RUNTIME)]
            counter = next(p['manifest'] for p in packages if p['manifest']['name'] == 'example.counter')
            self.assertEqual(counter['commands']['exposed'], ['get_value', 'set_value'])
            self.assertEqual(len(packages), 2)  # Command transport bridge is retained.
            if sys.platform == 'linux':
                from elftools.elf.elffile import ELFFile
                for library in (app/'build/host').glob('*/service.so'):
                    with library.open('rb') as stream:
                        elf = ELFFile(stream)
                        dynamic = elf.get_section_by_name('.dynamic')
                        self.assertIsNotNone(dynamic)
                        forbidden = {'DT_NEEDED', 'DT_INIT', 'DT_FINI', 'DT_INIT_ARRAY',
                                     'DT_FINI_ARRAY', 'DT_PREINIT_ARRAY'}
                        self.assertFalse(forbidden.intersection(tag.entry.d_tag for tag in dynamic.iter_tags()))
                        symbols = elf.get_section_by_name('.dynsym')
                        self.assertFalse([s.name for s in symbols.iter_symbols()
                                          if s.name and s.entry.st_shndx == 'SHN_UNDEF'])

    def test_deploy_recovery_and_invalid_graph(self):
        with tempfile.TemporaryDirectory(prefix='micros external host ') as temporary:
            app = create(Path(temporary)/'application')
            env = dict(os.environ, MICROS_SDK=str(ROOT))
            def call(action, *extra, ok=True):
                result = subprocess.run([str(app/'micros'), 'host', action, *map(str,extra)],
                                        cwd=temporary, env=env, capture_output=True, text=True, timeout=90)
                if ok: self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                else: self.assertNotEqual(result.returncode, 0, result.stdout)
                return result
            try:
                deployed = json.loads(call('deploy', '--runtime', RUNTIME).stdout)
                self.assertEqual(deployed['active'], {'example.hello':'1.0.1'})
                self.assertEqual(deployed['active'], deployed['last_good'])
                self.assertIn('Hello world', call('logs').stdout)
                self.assertTrue(json.loads(call('status').stdout)['running'])
                self.assertFalse((app/'build/build').exists())
                call('deploy', '--runtime', RUNTIME)  # Identical packages remain installable.
                call('stop')
                stopped = json.loads(call('status').stdout)
                self.assertFalse(stopped['running'])
                self.assertEqual(stopped['active'], {})
                call('boot', '--runtime', RUNTIME)
                contract = app/'services/hello/service.toml'
                contract.write_text(contract.read_text().replace('1.0.1', '1.0.2'))
                source = app/'services/hello/src/service.c'
                source.write_text(source.read_text().replace('return service_args->api->timer_open(',
                    'return MICROS_ERROR_INVALID_ARGUMENT;\n    return service_args->api->timer_open('))
                failed = call('deploy', '--runtime', RUNTIME, ok=False)
                self.assertIn('rolled back', failed.stderr)
                status = json.loads(call('status').stdout)
                self.assertEqual(status['requested'], {'example.hello':'1.0.2'})
                self.assertEqual(status['active'], {'example.hello':'1.0.1'})
                self.assertEqual(status['last_failure']['candidate'], status['requested'])
                self.assertEqual(status['last_failure']['attempt'], 2)
                self.assertTrue(status['last_failure']['reason'])
                call('stop'); call('boot', '--runtime', RUNTIME)
                self.assertEqual(json.loads(call('status').stdout)['active'], status['active'])
                # An invalid selection must not interrupt that running graph.
                project = app/'host.toml'
                project.write_text(project.read_text().replace('arena = "RAM"', 'arena = "PSRAM"'))
                call('deploy', '--runtime', RUNTIME, ok=False)
                self.assertEqual(json.loads(call('status').stdout)['active'], status['active'])
            finally:
                call('stop')


if __name__ == '__main__': unittest.main()
