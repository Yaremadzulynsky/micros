"""A developer's application composes and compiles outside the SDK checkout."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from micros_tooling.config.configuration import load_project, read_toml
from micros_tooling.config.composition import toml


class ExternalApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="external micros ")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.app = self.directory / "my application"
        self.env = dict(os.environ, MICROS_SDK=str(ROOT))
        self.env.pop("MICROS_STATE_DIR", None)
        self.env.pop("MICROS_APPLICATION_ROOT", None)
        result = self.run_cli(ROOT / "micros", "new", self.app)
        self.assertEqual(result.returncode, 0, result.stderr)

    def run_cli(self, launcher, *args):
        return subprocess.run([str(launcher), *map(str, args)], cwd=self.directory,
                              env=self.env, text=True, capture_output=True)

    def test_external_composition_generation_and_native_compilation(self):
        run = self.run_cli(self.app / "micros", "compose", "--json")
        self.assertEqual(run.returncode, 0, run.stderr)
        recipe = json.loads(run.stdout)
        self.assertEqual(Path(recipe['services'][0]['sources'][0]), self.app/'services/hello/src/service.c')
        run = self.run_cli(self.app/'micros', 'generate', '--json')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(len(json.loads(run.stdout)['services']), 1)
        generated = self.app/'build/services/hello/generated'
        self.assertTrue((generated/'hello_ipc.c').is_file())
        for source in (self.app/'services/hello/src/service.c', generated/'hello_ipc.c'):
            compiled = subprocess.run(['cc', '-std=c17', '-Wall', '-Wextra', '-Werror', '-ffreestanding',
                '-I', str(ROOT/'src/sdk/abi/include'), '-I', str(generated), '-c', str(source),
                '-o', str(self.app/'build'/(source.stem+'.o'))], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
        self.assertFalse((self.app/'.micros').exists())
        self.assertTrue((self.app/'micros.lock').is_file())

    def test_explicit_unit_generation_keeps_outputs_under_build(self):
        unit = self.app/'units/000000000000.toml'
        run = self.run_cli(self.app/'micros', 'generate', '--project', unit, '--json')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(all(Path(path).is_relative_to(self.app/'build') for path in json.loads(run.stdout)['headers']))
        self.assertFalse((self.app/'services/hello/generated').exists())

    def test_existing_project_is_preserved(self):
        source = self.app / "services/hello/src/service.c"
        source.write_text("developer edits\n")
        run = self.run_cli(ROOT / "micros", "new", self.app)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("already exists", run.stderr)
        self.assertEqual(source.read_text(), "developer edits\n")

    def test_multiple_units_require_explicit_device_for_composition(self):
        path = self.app/'units/000000000000.toml'
        (path.parent/'000000000001.toml').write_text(path.read_text().replace('000000000000', '000000000001'))
        run = self.run_cli(self.app/'micros', 'compose')
        self.assertNotEqual(run.returncode, 0)
        self.assertIn('Select -d', run.stderr)
        run = self.run_cli(self.app/'micros', 'generate', '--json')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertFalse((self.app/'.micros').exists())

    def test_explicit_private_state_is_not_modified_by_offline_commands(self):
        private = self.directory/'selected state'
        private.mkdir()
        (private/'recovery').write_text('preserve')
        self.env['MICROS_STATE_DIR'] = str(private)
        self.assertEqual(self.run_cli(self.app/'micros', 'compose').returncode, 0)
        self.assertEqual((private/'recovery').read_text(), 'preserve')
        self.assertEqual(sorted(p.name for p in private.iterdir()), ['recovery'])


if __name__ == "__main__":
    unittest.main()
