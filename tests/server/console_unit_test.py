"""Browser-free console checks; no npm install, network, account or hardware."""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
node = shutil.which("node")
if node is None:
    print("SKIP: install Node.js to run offline console checks.")
    raise SystemExit(77)
for name in ("flash_summary", "fleet_map", "log_output", "memory_summary", "scroll_refresh", "service_map"):
    subprocess.run([node, str(ROOT / "tests/server" / (name + "_test.cjs"))], cwd=ROOT, check=True)
