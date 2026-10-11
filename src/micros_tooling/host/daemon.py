"""User-local Unix-socket controller; management commands are serialized."""
import hashlib
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from micros_tooling.storage.packages import PackageError, canonical_json, read_json, require
from micros_tooling.host.native_process import NativeRuntime
from micros_tooling.storage.store import Store, atomic_write

REQUEST_LIMIT = 16384  # Fixed local control messages, never package/image payloads.
RESPONSE_LIMIT = 256 * 1024  # Bounded status/log reply, below installed-store metadata limit.
SOCKET_TIMEOUT = 30  # Exceeds native cooperative stop's bounded control deadline.


def socket_path(store):
    # Short paths fit macOS sockaddr_un even when the project path is long.
    directory = Path('/tmp') / f'micros-{os.getuid()}'
    directory.mkdir(mode=0o700, exist_ok=True)
    status = directory.lstat()
    require(not directory.is_symlink() and status.st_uid == os.getuid() and status.st_mode & 0o077 == 0,
            'local control directory must be private and user-owned')
    identifier = hashlib.sha256(str(store.root).encode()).hexdigest()[:24]
    return directory / f'{identifier}.sock'


def request(store, value):
    encoded = canonical_json(value)
    require(len(encoded) <= REQUEST_LIMIT, 'control request too large')
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(SOCKET_TIMEOUT)
        client.connect(str(socket_path(store)))
        client.sendall(encoded)
        output = b''
        while not output.endswith(b'\n'):
            chunk = client.recv(4096)
            require(chunk, 'control connection closed without reply')
            output += chunk
            require(len(output) <= RESPONSE_LIMIT, 'control response too large')
    result = read_json(output)
    require(result.get('ok'), result.get('error', 'control request failed'))
    return result['value']


def running(store):
    with (store.root / '.daemon-lock').open('a+b') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lock, fcntl.LOCK_UN)
            return False
        except BlockingIOError:
            return True


def logs(store, filename='runtime.log'):
    path = store.root / filename
    if not path.exists():
        return ''
    with path.open('rb') as stream:
        # Tail at most 32 KiB so JSON escaping remains below the response limit.
        stream.seek(max(0, os.fstat(stream.fileno()).st_size - 32 * 1024))
        return stream.read(32 * 1024).decode('utf-8', errors='replace')


def serve(root, executable):
    store = Store(root)
    path = socket_path(store)
    lock = (store.root / '.daemon-lock').open('a+b')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise PackageError('runtime already running')
    if path.exists():
        path.unlink()
    runtime = None
    try:
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(str(path)); os.chmod(path, 0o600)
            server.listen(4)  # Bounded pending local management connections.
            from micros_tooling.host.activation import boot_runtime
            runtime = boot_runtime(store, executable)
            atomic_write(store.root / 'runtime-state.json', canonical_json({'pid': os.getpid(), 'ready': True}))
            shutdown = False
            while not shutdown:
                connection, _ = server.accept()
                with connection:
                    connection.settimeout(SOCKET_TIMEOUT)
                    try:
                        encoded = b''
                        while not encoded.endswith(b'\n'):
                            chunk = connection.recv(4096)
                            require(chunk, 'incomplete request')
                            encoded += chunk
                            require(len(encoded) <= REQUEST_LIMIT, 'request too large')
                        value = read_json(encoded)
                        require(isinstance(value, dict), 'request must be an object')
                        action = value.get('action')
                        if action == 'status':
                            from micros_tooling.host.activation import read_record
                            result = runtime.status()
                            result['activation'] = read_record(store)
                            result['active'] = {s['name']: s['version'] for s in runtime.plan['services'] if s['name'] in runtime.instances}
                        elif action == 'logs': result = logs(store)
                        elif action == 'stop': result = runtime.stop(value.get('name'))
                        elif action == 'start': result = runtime.start(value.get('name'))
                        elif action == 'restart':
                            runtime.stop(value.get('name')); result = runtime.start(value.get('name'))
                        elif action == 'shutdown':
                            runtime.close(); runtime = None; shutdown = True; result = {'stopped': True}
                        else: raise PackageError('unknown local management action')
                        reply = {'ok': True, 'value': result}
                    except (PackageError, OSError, ValueError, KeyError, TypeError) as error:
                        reply = {'ok': False, 'error': str(error)}
                    try:
                        connection.sendall(canonical_json(reply))
                    except OSError:
                        pass  # A disconnected local client does not stop the service graph.
    except Exception as error:
        atomic_write(store.root / 'runtime-state.json', canonical_json({'pid': os.getpid(), 'ready': False, 'error': str(error)}))
        raise
    finally:
        if runtime is not None:
            runtime.close()
        path.unlink(missing_ok=True)
        lock.close()


def boot(store, executable):
    require(not running(store), 'runtime already running')
    from micros_tooling.host.activation import read_record
    if read_record(store) is None:
        store.plan()  # Legacy development boot; transactional boots use the durable record.
    state_path = store.root / 'runtime-state.json'
    state_path.unlink(missing_ok=True)
    entry = Path(__file__).resolve().parents[3] / 'tools' / 'cli' / 'microsctl.py'
    with (store.root / 'controller.log').open('wb') as log:
        process = subprocess.Popen([sys.executable, str(entry), '--store', str(store.root), '_serve',
                                    '--runtime', str(Path(executable).resolve())], stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=log, start_new_session=True)
    deadline = time.monotonic() + SOCKET_TIMEOUT
    while time.monotonic() < deadline:
        if state_path.exists():
            state = read_json(state_path.read_bytes())
            if state.get('pid') != process.pid:
                time.sleep(0.02)
                continue
            if state.get('ready'):
                return request(store, {'action': 'status'})
            raise PackageError(state.get('error', 'runtime boot failed'))
        require(process.poll() is None, 'runtime boot failed; inspect controller.log')
        time.sleep(0.02)  # 20 ms polling bounds startup CPU without delaying interactive CLI use.
    process.terminate()
    raise PackageError('runtime boot deadline')
