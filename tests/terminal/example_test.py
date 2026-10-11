"""Compile the actual example service and generated codecs against a simulated IPC boundary."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from micros_tooling.config.configuration import read_toml, generate_service_headers, load_project
from micros_tooling.config.composition import toml
from micros_tooling.config.protobuf import RUNTIME, RUNTIME_SOURCES
from micros_tooling.communication.channel_metadata import build, bind
from micros_tooling.storage.packages import digest, canonical_schema


class ExampleTests(unittest.TestCase):
    def test_example_builds_and_processes_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            shutil.copytree(ROOT / 'examples/shell-service', directory, dirs_exist_ok=True,ignore=shutil.ignore_patterns('build'))
            recipe = read_toml(directory / 'micros.toml')
            del recipe['services']['bridge']
            project = directory / 'micros.toml'
            project.write_text(toml(recipe))
            generate_service_headers(project)
            service = load_project(project)['services'][0]
            generated = Path(service['_contract']['directory']) / 'generated'
            binary = directory / 'test'
            subprocess.run(['cc', '-std=c17', '-Wall', '-Wextra', '-Werror', '-UNDEBUG',
                            '-I'+str(ROOT/'src/sdk/abi/include'), '-I'+str(ROOT/'src/sdk/abi/internal'),
                            '-I'+str(RUNTIME), '-I'+str(directory/'src'), '-I'+str(generated),
                            str(ROOT/'tests/terminal/example_test.c'),
                            str(generated/'shell_demo_ipc.c'),
                            str(Path(service['_interface']['directory'])/'generated/shell_demo_bindings.c'),
                            *map(str, generated.glob('*.pb.c')), *map(str, RUNTIME_SOURCES),
                            '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_metadata_discovers_published_ports_without_local_source_at_runtime(self):
        packages = []
        for service in load_project(ROOT/'examples/shell-service/micros.toml')['services']:
            packages.append(dict(manifest=dict(name=service['name'], version=service['version'],
                channels=service['channels'], published_ports=build(service), ipc_bridge=service['_interface']['name']=='bridge',
                schemas={k:digest(canonical_schema(Path(v).read_bytes())) for k,v in service['schemas'].items()})))
        bindings = bind(packages)
        self.assertEqual({b['port']['name'] for b in bindings}, {'status'})
        self.assertEqual({b['service'] for b in bindings}, {'example.shell'})


if __name__ == '__main__':
    unittest.main()
