"""Compile production monitor with generated contracts and simulated GPIO/ADC."""
from pathlib import Path
import subprocess
import sys
import tempfile
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from micros_tooling.config.configuration import config_artifacts, load_project
recipe = load_project(ROOT / "examples/pin-monitor/micros.toml")
spec = recipe["services"][0]["_configuration"]
_, payload = config_artifacts(spec["name"], spec["definition"], spec["values"])
with tempfile.TemporaryDirectory() as directory:
    config = Path(directory) / "config.bin"
    config.write_bytes(payload)
    binary = Path(directory) / "monitor-test"
    subprocess.run(["cc", "-std=c17", "-Wall", "-Wextra", "-Werror",
                    '-DMONITOR_CONFIG_FILE="' + str(config) + '"',
                    "-I" + str(ROOT / "src/sdk/abi/include"), "-I" + str(ROOT / "src/third_party/nanopb"),
                    str(ROOT / "tests/services/pin_monitor_test.c"), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)

# Exercise the CSV reader with the real generated Python protobuf decoder.
import contextlib
import io
from unittest.mock import Mock, patch
from micros_tooling.communication import pin_monitor
remote = Mock()
remote.request.side_effect = [
    {"reply": "IPC DATA 1 080110e8071822200128801038e807"}, KeyboardInterrupt()]
output = io.StringIO()
with patch.object(sys, "argv", ["pin-monitor", "--device", "001122334455", "--project",
                               str(ROOT / "examples/pin-monitor/micros.toml")]), \
     patch.object(pin_monitor, "configured_remote", return_value=remote), \
     contextlib.redirect_stdout(output):
    pin_monitor.main()
assert "1000,1,1000,34,1,2048,0" in output.getvalue()
remote.request.assert_called_with("POST", "/v1/platform-command", b"IPC READ 0 1")
print("PASS CSV reader uses deployed bridge instance and shared protobuf contract")
