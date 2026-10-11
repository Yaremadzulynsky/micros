"""Run the physical driver/LED service sources unchanged on simulated host GPIO."""
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from micros_tooling.storage.packages import build_package
from micros_tooling.host.native_process import NativeRuntime
from micros_tooling.storage.store import Store
from tools.packaging.demo_packages import manifest

build = Path(sys.argv[1]).resolve()
schema = (Path(__file__).resolve().parents[2] / 'src/sdk/protos/button/v1/button_state.proto').read_bytes()
with tempfile.TemporaryDirectory() as temporary:
    store = Store(Path(temporary))
    selection = {}
    for role in (0, 1, 3):
        image = (build / f'board_{role}.mimg').read_bytes()
        description = manifest(f'board.role{role}', 'publish' if role == 0 else 'subscribe', image, schema)
        # Host handles are 64-bit: legacy button fixture owns handles and sampling state;
        # logger owns one handle, sequence, epoch and timestamp; the legacy LED fixture uses 40 bytes.
        description['memory']['arena_bytes'] = {0: 40, 1: 32, 3: 40}[role]
        if role in (0, 3):
            description['capabilities']['gpio'] = [1 if role == 0 else 0]
            description['capabilities']['handles'] += 1
        store.install(build_package(description, image, {'sample': schema}))
        selection[description['name']] = '1.0.0'
    store.configure(selection)
    runtime = NativeRuntime(store, build / 'micros-control', store.plan())
    try:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            text = (store.root / 'runtime.log').read_text()
            if 'LED level=1 verified' in text and 'LATENCY_US=' in text: break
            time.sleep(0.01)
        else: raise AssertionError('driver/IPC/LED path did not execute')
    finally: runtime.close()
print('Hardware service sources execute against the host GPIO simulator')
