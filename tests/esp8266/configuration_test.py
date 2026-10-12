"""Reject a toolchain mode that cannot parse the shared controller protocol."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ConfigurationTests(unittest.TestCase):
    def test_nano_format_is_rejected_before_component_build(self):
        # Execute the production CMake guard. No ESP SDK or hardware is needed:
        # a stale/custom sdkconfig must fail before SDK component registration.
        result = subprocess.run(
            ['cmake', '-DCONFIG_NEWLIB_NANO_FORMAT=ON', '-P',
             str(ROOT / 'src/firmware/platforms/esp8266/sdk/main/CMakeLists.txt')],
            capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Micros RPC and telemetry require 64-bit printf/scanf', result.stderr)


if __name__ == '__main__':
    unittest.main()
