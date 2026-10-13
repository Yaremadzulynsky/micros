"""Production IR driver with simulated registers; no hardware or transmissions."""
from pathlib import Path
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT / "src"))
from micros_tooling.config.configuration import generate_service_headers
# Actual generated contracts are used by the production source included in C.
generate_service_headers(ROOT/'tests/fixtures/ir/micros.toml',None)
with tempfile.TemporaryDirectory() as temp:
    binary=Path(temp)/'ir-test'
    subprocess.run(['cc','-std=c17','-Wall','-Wextra','-Werror',
                    '-I'+str(ROOT/'src/sdk/abi/include'),'-I'+str(ROOT/'src/third_party/nanopb'),
                    str(ROOT/'tests/services/ir_service_test.c'),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
