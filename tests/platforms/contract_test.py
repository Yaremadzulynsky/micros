"""Compile the actual shared controller against one independent, SDK-free port."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = ROOT / 'src/firmware'
CONTRACTS = FIRMWARE / 'contracts/include'
FAKE = Path(__file__).parent / 'fake'
HEADERS = {'platform.h', 'storage.h', 'transport.h', 'network.h', 'update.h', 'telemetry.h', 'capabilities.h', 'memory.h'}

class PlatformContractTest(unittest.TestCase):
    def test_platform_layout_exposes_only_contract_implementations(self):
        implementations = {'platform', 'storage', 'transport', 'network', 'update', 'telemetry'}
        for platform in ('posix', 'esp32', 'esp8266', 'samd21'):
            with self.subTest(platform=platform):
                root = FIRMWARE / 'platforms' / platform
                self.assertTrue((root / 'target_config.h').is_file())
                self.assertTrue((root / 'sdk').is_dir())
                public = [path for path in (root / 'src').iterdir() if path.is_file()]
                self.assertEqual({path.stem for path in public}, implementations)
                self.assertTrue(all(path.suffix in ('.c', '.cpp') for path in public))
                self.assertEqual({path.name for path in (root / 'src').iterdir() if path.is_dir() and any(path.iterdir())}, {'support'})

    def includes(self, selected=FAKE):
        paths = [selected, CONTRACTS, ROOT / 'src/sdk/abi/include', FIRMWARE / 'controller/include']
        paths += [FIRMWARE / 'kernel' / name for name in ('runtime', 'ipc', 'loader', 'deployment', 'hash')]
        return ['-I' + str(path) for path in paths]

    def test_one_contract_surface_in_c_and_cpp(self):
        self.assertEqual({p.name for p in (CONTRACTS / 'micros').glob('*.h')}, HEADERS)
        for header in sorted(HEADERS):
            for language, compiler, standard in [('c', 'cc', 'c17'), ('c++', 'c++', 'c++17')]:
                with self.subTest(header=header, language=language):
                    result = subprocess.run([compiler, '-x', language, '-std=' + standard, '-Wall', '-Wextra', '-Werror',
                                             '-fsyntax-only', *self.includes(), '-'],
                                            input='#include <micros/' + header + '>\n', text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_fresh_port_links_real_controller_and_rejects_missing_operation(self):
        shared = [FIRMWARE / 'controller' / name for name in ('controller.c', 'deployment.c', 'application.c',
                  'status.c', 'protocol/ipc_console.c')]
        shared += [FIRMWARE / 'kernel' / name for name in ('runtime/runtime.c', 'ipc/channel.c', 'loader/image.c',
                   'loader/elf.c', 'deployment/activation.c', 'hash/sha256.c')]
        sources = shared + sorted(path for path in (FAKE / 'src').glob('*.c') if path.name != 'main.c')
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            # Reference every declared operation, including optional unsupported
            # implementations that the current controller may not call yet.
            names = set()
            for header in HEADERS:
                source = (CONTRACTS / 'micros' / header).read_text()
                source = re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S)
                names.update(re.findall(r'\b(micros_\w+)\s*\(', source))
            surface = out / 'surface.c'
            surface.write_text(''.join('#include <micros/' + header + '>\n' for header in sorted(HEADERS)) +
                'static void (*volatile operations[])(void) = {\n' +
                ',\n'.join('(void (*)(void))' + name for name in sorted(names)) +
                '\n};\nint main(void) { return operations[0] == 0; }\n')
            sources.append(surface)
            objects = [out / (str(index) + '.o') for index in range(len(sources))]
            def compile_one(index, *flags):
                result = subprocess.run(['cc', '-std=c17', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                    *self.includes(), *flags, '-c', str(sources[index]), '-o', str(objects[index])], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            for index in range(len(sources)): compile_one(index)
            result = subprocess.run(['cc', *map(str, objects), '-o', str(out / 'port')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            # This double cannot execute native code. Linking is the boundary being checked.
            compile_one(sources.index(FAKE / 'src/platform.c'), '-DOMIT_REQUIRED_OPERATION=1')
            result = subprocess.run(['cc', *map(str, objects), '-o', str(out / 'missing')], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('micros_controller_yield', result.stderr)

    def test_explicit_capabilities_reject_unsupported_builds(self):
        for language, compiler, standard in [('c', 'cc', 'c17'), ('c++', 'c++', 'c++17')]:
            for capability, supported in [('NATIVE_SERVICES', True), ('BASE_UPDATE', False), ('ANALOG_GPIO', False)]:
                with self.subTest(language=language, capability=capability):
                    result = subprocess.run([compiler, '-x', language, '-std=' + standard, '-fsyntax-only',
                        *self.includes(), '-DMICROS_REQUIRE_' + capability + '=1', '-'],
                        input='#include <micros/capabilities.h>\n', capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, supported, result.stderr)
            with tempfile.TemporaryDirectory() as directory:
                (Path(directory) / 'target_config.h').write_text('#define MICROS_CAP_NATIVE_SERVICES 1\n')
                result = subprocess.run([compiler, '-x', language, '-std=' + standard, '-fsyntax-only',
                    *self.includes(Path(directory)), '-'], input='#include <micros/capabilities.h>\n', capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Target must declare', result.stderr)

if __name__ == '__main__': unittest.main()
