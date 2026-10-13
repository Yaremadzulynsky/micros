"""Run the hello service with real runtime timers and observe serial diagnostics."""
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
with tempfile.TemporaryDirectory() as temporary:
    store = Store(Path(temporary))
    image = (build / 'minimal_c.mimg').read_bytes()
    description = manifest('example.hello', 'publish', image, b'')
    description.update(channels=[], schemas={},
                       memory=dict(arena_bytes=8, arena_alignment=8, stack_bytes=4096),
                       capabilities=dict(handles=1, timers=1, gpio=[]))
    store.install(build_package(description, image, {}))
    store.configure({'example.hello': '1.0.0'})
    started = time.monotonic()
    runtime = NativeRuntime(store, build / 'micros-control', store.plan())
    # Activation includes a five-second health trial. Measure three subsequent
    # timer events, excluding messages retained during confirmation.
    baseline = (store.root / 'runtime.log').read_text().count('Hello world\n')
    started = time.monotonic()
    observed = []
    try:
        while time.monotonic() - started < 4:
            count = (store.root / 'runtime.log').read_text().count('Hello world\n') - baseline
            while len(observed) < count:
                observed.append(time.monotonic() - started)
            if len(observed) >= 3:
                break
            time.sleep(0.01)
        assert len(observed) == 3, observed
        assert 0 <= observed[0] <= 1.3, observed
        # Allow host scheduling jitter while rejecting busy-loop or doubled-rate output.
        assert all(0.8 <= later - earlier <= 1.3
                   for earlier, later in zip(observed, observed[1:])), observed
    finally:
        runtime.close()
    stopped_count = (store.root / 'runtime.log').read_text().count('Hello world\n')
    time.sleep(1.1)
    assert (store.root / 'runtime.log').read_text().count('Hello world\n') == stopped_count
print('Hello world repeats once per second and stops cleanly')
