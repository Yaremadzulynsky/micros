"""Compile and exercise the generated adapter with protobuf and adversarial outcomes."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from micros_tooling.config.interfaces import ipc_artifacts
from micros_tooling.config.coordination_codegen import callback_artifacts
from micros_tooling.storage.packages import PackageError
from micros_tooling.config.protobuf import compile_schema, RUNTIME, RUNTIME_SOURCES


class CoordinationCallbacksTest(unittest.TestCase):
    def test_reserved_adapter_name(self):
        with self.assertRaisesRegex(PackageError, 'reserved'):
            callback_artifacts('demo', [dict(name='coordination', kind='state')])

    def test_generated_lifecycle_and_delivery(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            generated = directory / 'generated'
            generated.mkdir()
            schema = str(ROOT / 'src/sdk/protos/coordination/v1/target.proto')
            protocol = compile_schema(schema)
            ports = [dict(name=name, kind=kind, access=access, key=index + 1,
                          schema=schema, max_payload=16)
                     for index, (name, kind, access) in enumerate([
                         ('target', 'state', 'publish'), ('observed', 'state', 'subscribe'),
                         ('command', 'action', 'publish'), ('execute', 'action', 'subscribe'),
                         ('event_out', 'event', 'publish'), ('event_in', 'event', 'subscribe')])]
            header, source = ipc_artifacts(dict(name='demo', directory=str(directory), ports=ports),
                                           {schema: protocol})
            (generated / 'demo_ipc.h').write_text(header)
            (generated / 'demo_ipc.c').write_text(source)
            for filename, content in protocol['files'].items():
                (generated / filename).write_text(content)
            executable = directory / 'check'
            command = ['cc', '-std=c17', '-Wall', '-Wextra', '-Werror', '-pedantic-errors',
                       '-I', str(directory), '-I', str(ROOT / 'src/sdk/abi/include'),
                       '-I', str(ROOT / 'src/sdk/abi/internal'), '-I', str(RUNTIME),
                       str(ROOT / 'tests/interfaces/coordination_callbacks.c'),
                       str(generated / 'demo_ipc.c'),
                       *map(str, generated.glob('*.pb.c')), *map(str, RUNTIME_SOURCES),
                       '-o', str(executable)]
            subprocess.run(command, check=True)
            subprocess.run([str(executable)], check=True)
            # Low-level users do not need the lifecycle macro or its context getter.
            legacy = directory / 'legacy.c'
            legacy.write_text('#include "generated/demo_ipc.h"\nint main(void) { return 0; }\n')
            legacy_command = [str(legacy) if arg == str(ROOT / 'tests/interfaces/coordination_callbacks.c') else arg
                              for arg in command]
            subprocess.run(legacy_command, check=True)
            # Including the generated API also remains valid in a C++ service.
            subprocess.run(['c++', '-std=c++17', '-pedantic-errors', '-fsyntax-only',
                            '-x', 'c++', '-I', str(ROOT / 'src/sdk/abi/include'), '-I', str(RUNTIME),
                            str(generated / 'demo_ipc.h')], check=True)


if __name__ == '__main__':
    unittest.main()
