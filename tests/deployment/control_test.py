"""Exercise the public CLI, boot reconstruction, and pre-execution admission."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from micros_tooling.storage.packages import PackageError, build_package, canonical_json, read_package
from micros_tooling.host.native_process import NativeRuntime
from micros_tooling.storage.store import Store
from micros_tooling.host import daemon
from tools.packaging.demo_packages import build_demo

build = Path(sys.argv[1]).resolve()
cli = Path(__file__).resolve().parents[2] / 'tools/cli/microsctl.py'
with tempfile.TemporaryDirectory(prefix='micros-control-test-') as temporary:
    root = Path(temporary)
    selection = build_demo(build, root / 'packages')
    store = Store(root / 'store')
    def command(*arguments, success=True):
        result = subprocess.run([sys.executable, str(cli), '--store', str(store.root), *map(str, arguments)],
                                text=True, capture_output=True, timeout=15)
        assert (result.returncode == 0) == success, result.stdout + result.stderr
        return json.loads(result.stdout) if success and result.stdout else result.stderr
    try:
        for name in ('publisher', 'fast', 'slow'): command('install', root / 'packages' / f'{name}.msp')
        command('configure', root / 'packages' / 'enabled.json')
        initial_plan = command('plan')
        booted = command('boot', '--runtime', build / 'micros-control')
        assert len(booted['services']) == 3 and all(status['state'] == 'Running' for status in booted['services'].values())
        assert 'already running' in command('boot', '--runtime', build / 'micros-control', success=False)
        assert 'shutdown' in command('disable', 'demo.slow', success=False)
        deadline = time.monotonic() + 5
        while 'slow logger: messages missed' not in command('logs'):
            assert time.monotonic() < deadline
            time.sleep(0.05)
        command('stop', 'demo.slow')
        assert len(command('status')['services']) == 2
        command('start', 'demo.slow')
        command('restart', 'demo.fast')
        command('shutdown')
        assert command('plan') == initial_plan
        (store.root / 'images' / 'unused.mimg').write_bytes(b'old generated cache')
        cached = next(path for path in (store.root / 'images').glob('*.mimg') if path.name != 'unused.mimg')
        cached.write_bytes(b'corrupted derived cache')
        restored = command('boot', '--runtime', build / 'micros-control')
        assert set(restored['services']) == set(selection)
        assert not (store.root / 'images' / 'unused.mimg').exists()
        command('shutdown')
    finally:
        if daemon.running(store): daemon.request(store, {'action': 'shutdown'})
    # A manifest understating memory is detected by the real native descriptor,
    # before ANY service hook executes in the candidate graph.
    bad_store = Store(root / 'bad-store')
    for name in ('publisher', 'fast', 'slow'):
        blob = (root / 'packages' / f'{name}.msp').read_bytes()
        package = read_package(blob)
        if name == 'fast':
            package['manifest']['memory']['arena_bytes'] -= 1
            blob = build_package(package['manifest'], package['image'], package['schemas'])
        bad_store.install(blob)
    bad_store.configure(selection)
    try:
        NativeRuntime(bad_store, build / 'micros-control', bad_store.plan())
    except PackageError as error:
        assert 'descriptor memory mismatch' in str(error), error
    else: raise AssertionError('manifest/native mismatch accepted')
    # Controller recovery events are diagnostics; no application hook may run.
    rejected_log = (bad_store.root / 'runtime.log').read_text()
    assert all(line.startswith(('AUTOBOOT REJECT', 'ROLLBACK attempts exhausted'))
               for line in rejected_log.splitlines()), rejected_log
    # An undeclared IPC capability is rejected by the kernel, even when the
    # service's independently compiled code attempts to open its normal channel.
    denied_store = Store(root / 'denied-store')
    package = read_package((root / 'packages' / 'publisher.msp').read_bytes())
    package['manifest']['channels'] = []
    denied_store.install(build_package(package['manifest'], package['image'], package['schemas']))
    denied_store.configure({'demo.publisher': '1.0.0'})
    try:
        NativeRuntime(denied_store, build / 'micros-control', denied_store.plan())
    except PackageError as error:
        assert 'launch failed' in str(error), error
    else: raise AssertionError('undeclared capability accepted')
print('PASS CLI install/configure/boot/status/logs/start/stop/restart, saved boot reconstruction, descriptor mismatch before hooks, and kernel capability rejection')
