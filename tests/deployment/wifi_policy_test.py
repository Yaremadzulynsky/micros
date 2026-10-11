"""Run the production Wi-Fi controller against a deterministic ESP-IDF adapter."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

class WifiPolicyTests(unittest.TestCase):
    def test_controller(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("esp_event.h", "esp_netif.h", "esp_timer.h", "esp_wifi.h",
                         "freertos/FreeRTOS.h", "nvs.h", "nvs_flash.h", "sdkconfig.h"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("/* Types and behavior supplied by the test adapter. */\n")
            binary = root / "wifi-policy"
            subprocess.run(["cc", "-std=c11", "-D_POSIX_C_SOURCE=200809L", "-Wall", "-Wextra", "-Werror",
                            "-fsanitize=address,undefined", "-I" + str(root),
                            "-I" + str(ROOT / "src/firmware/controller/include"),
                            str(ROOT / "tests/deployment/wifi_policy_test.c"),
                            str(ROOT / "src/firmware/controller/support/wifi_credentials.c"),
                            "-o", str(binary)], check=True, capture_output=True)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("70617373776f7264", result.stdout)
            self.assertNotIn("password", result.stdout)

if __name__ == "__main__":
    unittest.main()
