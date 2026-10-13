"""Wire integers must work on both full and reduced embedded C libraries."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

class IntegerTests(unittest.TestCase):
    def test_native_c_and_cpp(self):
        with tempfile.TemporaryDirectory() as directory:
            for compiler, language, standard in [('cc', 'c', 'c17'), ('c++', 'c++', 'c++17')]:
                output = Path(directory) / language
                subprocess.run([compiler, '-x', language, '-std='+standard, '-Wall', '-Wextra', '-Werror',
                    '-pedantic', str(ROOT/'tests/platforms/integer_test.c'), '-o', str(output)], check=True)
                subprocess.run([str(output)], check=True, timeout=10)

    def test_no_optional_integer_formats_in_firmware(self):
        # A host printf test cannot detect newlib-nano incompatibility. Prevent
        # new wide/size_t libc conversions from bypassing the shared helpers.
        forbidden = re.compile(r'\b(?:PRI|SCN)[diouxX](?:64|MAX|PTR)\b|%[-+ #0-9.*]*(?:ll|j|z|t)[diouxX]')
        for path in (ROOT/'src/firmware').rglob('*'):
            if path.suffix in ('.c', '.h', '.cpp', '.inc'):
                self.assertIsNone(forbidden.search(path.read_text()), str(path.relative_to(ROOT)))

    def test_arm_full_and_nano(self):
        compiler = os.environ.get('MICROS_ARM_GCC') or shutil.which('arm-none-eabi-gcc')
        emulator = shutil.which('qemu-system-arm')
        if not compiler or not emulator:
            if os.environ.get('MICROS_REQUIRE_NANO_TEST'):
                self.fail('ARM GCC and qemu-system-arm are required')
            self.skipTest('set MICROS_ARM_GCC and install qemu-system-arm for the nano regression')
        with tempfile.TemporaryDirectory() as directory:
            for library in ('full', 'nano'):
                output = Path(directory) / (library+'.elf')
                subprocess.run([compiler, '-mcpu=arm926ej-s', '--specs=rdimon.specs',
                    *(['--specs=nano.specs'] if library == 'nano' else []),
                    '-std=c17', '-Wall', '-Wextra', '-Werror', str(ROOT/'tests/platforms/integer_test.c'),
                    '-o', str(output)], check=True)
                result = subprocess.run([emulator, '-M', 'versatilepb', '-cpu', 'arm926', '-nographic',
                    '-semihosting', '-kernel', str(output)], capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                self.assertIn('portable integers passed', result.stdout+result.stderr)

if __name__ == '__main__': unittest.main()
