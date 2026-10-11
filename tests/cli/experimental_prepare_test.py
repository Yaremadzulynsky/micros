"""USB preparation bootstraps missing tools without entering a device transport."""
import argparse
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from micros_tooling.platforms.esp8266 import cli as esp
from micros_tooling.platforms.samd21 import cli as samd
from micros_tooling.deployment import samd_enrollment as enrollment
from micros_tooling.storage.packages import PackageError


class PrepareTest(unittest.TestCase):
    def test_esp_missing_tools_setup_before_build_without_usb(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(esp, 'ROOT', Path(directory)), \
                 patch.object(esp, 'profile_path', return_value=Path(directory)/'profile'), \
                 patch('micros_tooling.platforms.esp8266.bootstrap.setup') as setup, \
                 patch.object(esp.subprocess, 'run') as run, \
                 patch.object(esp, 'connect') as connect, contextlib.redirect_stdout(io.StringIO()):
                esp.main(argparse.Namespace(command='init', name='test', phase='prepare', firmware=None))
                setup.assert_called_once_with(Path(directory))
                run.assert_called_once()
                connect.assert_not_called()

    def test_esp_existing_tools_do_not_reinstall(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ['build/toolchains/esp8266-rtos-sdk-v3.4',
                         'build/toolchains/xtensa-lx106-elf/bin/xtensa-lx106-elf-gcc',
                         'build/esp8266/python/bin/python']:
                path = root/name; path.parent.mkdir(parents=True, exist_ok=True); path.touch()
            with patch.object(esp, 'ROOT', root), patch.object(esp, 'profile_path', return_value=root/'profile'), \
                 patch('micros_tooling.platforms.esp8266.bootstrap.setup') as setup, \
                 patch.object(esp.subprocess, 'run'), contextlib.redirect_stdout(io.StringIO()):
                esp.main(argparse.Namespace(command='init', name='test', phase='prepare', firmware=None))
                setup.assert_not_called()

    def test_mkr_prepare_uses_validated_compiler_without_usb(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); project=root/'unit.toml';project.write_text('[services]\n')
            args=argparse.Namespace(command='init',name='test',phase='prepare',project=project,
                                    compiler_dir=root/'compiler',json=True)
            with patch.object(samd, 'ROOT', root), patch.object(samd, 'profile_path', return_value=root/'profile'), \
                 patch.object(enrollment, 'prepare_tools', return_value=root/'compiler') as setup, \
                 patch.object(samd.subprocess,'run') as run, patch.object(samd,'SerialRemote') as serial, \
                 contextlib.redirect_stdout(io.StringIO()):
                samd.main(args)
                setup.assert_called_once_with(root/'build/samd21',root/'compiler')
                self.assertEqual(run.call_args.args[0][-1],str(root/'compiler'))
                serial.assert_not_called()

    def test_mkr_missing_compiler_stops_before_download(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(enrollment.shutil,'which',return_value=None), \
             patch.object(Path,'is_file',return_value=False), \
             patch('micros_tooling.deployment.enrollment.run_tool') as run:
            with self.assertRaisesRegex(PackageError,'complete ARM GCC'):
                enrollment.prepare_tools(Path(directory))
            run.assert_not_called()

    def test_mkr_unexpected_dependency_revision_is_preserved(self):
        from micros_tooling.deployment import enrollment as common
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); compiler=root/'compiler';compiler.mkdir()
            for tool in ('gcc','g++','objcopy'):
                (compiler/('arm-none-eabi-'+tool)).touch()
            (root/'Library/Arduino15/packages/arduino/hardware/samd/1.8.13').mkdir(parents=True)
            (root/'build/toolchains/freertos-kernel-v11.1.0').mkdir(parents=True)
            with patch.object(common,'ROOT',root), patch.object(Path,'home',return_value=root), \
                 patch.object(enrollment.shutil,'which',return_value='/arduino-cli'), \
                 patch.object(common,'run_tool',side_effect=['10.2.1','unexpected']) as run:
                with self.assertRaisesRegex(PackageError,'pinned revision'):
                    enrollment.prepare_tools(root/'session',compiler)
                self.assertEqual(run.call_count,2)
                self.assertNotIn('clone',run.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
