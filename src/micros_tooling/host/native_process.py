"""Single-controller bridge to the native host lifecycle manager."""
import json
import os
import threading
from pathlib import Path
import select
import subprocess
import time
from micros_tooling.storage.packages import PackageError, require

# Native stop permits a current hook plus cleanup; five seconds also bounds a
# failed controller pipe without pretending a blocked native thread is reclaimable.
CONTROL_TIMEOUT = 5
START_TIMEOUT = 2
POLL_SECONDS = 0.005


class NativeRuntime:
    """Admits the whole graph before hooks run, then serializes native management requests."""
    def __init__(self, store, executable, plan=None):
        self.store, self.executable = store, str(Path(executable).resolve())
        self.instances = {}
        self.session = os.urandom(16).hex()
        self.log_error = None
        self.catalog = store.metadata('controller-catalog.json', {'banks': {}})
        if plan is not None and not plan['services']:
            self.plan = plan
            self._spawn()
            return  # Descriptor inspection uses the shared runtime without activation.
        if plan is not None:
            from micros_tooling.storage.store import atomic_write
            from micros_tooling.storage.packages import canonical_json
            requested = {service['name']: service['version'] for service in plan['services']}
            atomic_write(store.root / 'activation-request.json', canonical_json(requested))
        self._spawn()
        try:
            status = self._settle()
            requested = store.metadata('activation-request.json', None)
            if requested is None and status['activation']['good'] == 0xFFFFFFFF:
                requested = store.selection()['enabled']
            if requested is not None:
                self._deploy(requested, status)
                status = self._settle()
            good = status['activation']['good']
            if requested is not None and self.catalog['banks'].get(str(good), {}).get('selection') != requested:
                from micros_tooling.storage.store import atomic_write
                from micros_tooling.storage.packages import canonical_json
                failure = status.get('last_failure', {})
                atomic_write(store.root / 'last-failure.json', canonical_json(dict(
                    candidate=requested, attempt=failure.get('attempts', 0),
                    reason=failure.get('reason', 'native controller rejected candidate'))))
            entry = self.catalog['banks'].get(str(good))
            require(entry is not None and status['services'],
                    'application launch failed or descriptor memory mismatch; inspect runtime.log')
            self.plan = store.plan(entry['selection'])
            self.instances = {service['name']: int(actual['instance'])
                              for service, actual in zip(self.plan['services'], status['services'])}
            require(len(self.instances) == len(self.plan['services']), 'native service catalog mismatch')
            # Cache cleanup affects derived package copies only, never native confirmed banks.
            retained = {service['package_sha256'] + '.mimg' for service in self.plan['services']}
            for cached in (store.root / 'images').glob('*.mimg'):
                if cached.name not in retained: cached.unlink()
        except Exception:
            self.close()
            raise

    def _spawn(self):
        self.process = subprocess.Popen([self.executable], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
            env={**os.environ, 'MICROS_CONTROLLER_STORE': str(self.store.root / 'controller')})
        self.log_thread = threading.Thread(target=self.capture_logs, daemon=True)
        self.log_thread.start()

    def _dispose(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=CONTROL_TIMEOUT)
        self.process.stdin.close()
        self.process.stdout.close()
        self.log_thread.join(timeout=CONTROL_TIMEOUT)
        self.process.stderr.close()

    def rpc(self, operation, bank=0, slot=0, cursor=0, body=b'', allow_error=False):
        return self.command(f'RPC {operation} {bank} {slot} {cursor} {self.session} {body.hex() or "-"}',
                            allow_error=allow_error, timeout=15)

    def _settle(self):
        # Restart only a controller-requested whole-process reset. Trial counts,
        # fallback and confirmation remain entirely inside the shared controller.
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            try:
                status = self.rpc(0)
                if not status['activation']['pending']:
                    return status
            except (PackageError, OSError):
                try: code = self.process.wait(timeout=1)
                except subprocess.TimeoutExpired: raise
                require(code == 75, 'native controller failed; inspect runtime.log')
                self._dispose()
                self._spawn()
            time.sleep(.025)
        raise PackageError('native activation deadline; inspect runtime.log')

    def _deploy(self, selection, status):
        import hashlib
        import struct
        from micros_tooling.storage.deployment import encode_graph
        from micros_tooling.storage.store import atomic_write
        from micros_tooling.storage.packages import canonical_json
        native = status['activation']
        previous = self.catalog['banks'].get(str(native['good']), {})
        requested_path = self.store.root / 'activation-request.json'
        submitted = self.catalog.get('submitted')
        # A native reset can interrupt the response after persisting the trial.
        # Observe its sequence; never reset an already-consumed boot attempt.
        if submitted and submitted['selection'] == selection and native['sequence'] > submitted['sequence']:
            requested_path.unlink(missing_ok=True)
            return
        if previous.get('selection') == selection:
            requested_path.unlink(missing_ok=True)
            return
        plan = self.store.plan(selection)
        bank = 1 - native['good'] if native['good'] in (0, 1) else 0
        slots = {service['name']: index for index, service in enumerate(plan['services'])}
        lines = dict(gpio=[dict(name=f'line{i}', line=i, pin=pin, direction='output')
                          for i, pin in enumerate((2, 4, 5, 16))], recovery_button=None)
        graph = encode_graph(plan, bank, slots, lines)
        images = [self.store.materialize(service).read_bytes() for service in plan['services']]
        digest = hashlib.sha256(graph + b''.join(images)).digest()
        self.rpc(8, body=bytes.fromhex(native['good_sha256']) + struct.pack('<I', native['sequence']))
        self.rpc(5)
        for slot, data in enumerate(images + [graph]):
            graph_record = slot == len(images)
            operation = 22 if graph_record else 19
            slot = 0 if graph_record else slot
            self.rpc(operation, bank, slot, body=struct.pack('<I', len(data)))
            for offset in range(0, len(data), 256):
                self.rpc(operation + 1, bank, slot, offset, data[offset:offset + 256])
            self.rpc(operation + 2, bank, slot)
        self.catalog['banks'][str(bank)] = dict(selection=selection, digest=digest.hex())
        self.catalog['submitted'] = dict(selection=selection, sequence=self.rpc(0)['activation']['sequence'])
        atomic_write(self.store.root / 'controller-catalog.json', canonical_json(self.catalog))
        try:
            self.rpc(4, bank, body=digest)
            self.rpc(9)
        except (PackageError, OSError):
            # Reset is acknowledged by the process exit code, never inferred from
            # a timeout or an unrelated crash.
            try: code = self.process.wait(timeout=1)
            except subprocess.TimeoutExpired: raise
            require(code == 75, 'native activation failed; inspect runtime.log')
            self._dispose()
            self._spawn()
        requested_path.unlink(missing_ok=True)

    def capture_logs(self):
        # Two 1 MiB files bound persisted diagnostics independently of service rate.
        limit = 1024 * 1024
        path = self.store.root / 'runtime.log'
        stream = path.open('ab', buffering=0)
        try:
            while True:
                chunk = os.read(self.process.stderr.fileno(), 4096)  # One bounded pipe read.
                if not chunk:
                    break
                if stream.tell() + len(chunk) > limit:
                    stream.close()
                    os.replace(path, self.store.root / 'runtime.log.1')
                    stream = path.open('wb', buffering=0)
                stream.write(chunk)
        except OSError as error:
            self.log_error = str(error)
        finally:
            stream.close()

    def command(self, text, allow_error=False, timeout=CONTROL_TIMEOUT):
        require(self.process.poll() is None, 'native runtime exited; inspect runtime.log')
        require(self.log_error is None, f'diagnostic storage failed: {self.log_error}')
        self.process.stdin.write(text.encode() + b'\n')
        self.process.stdin.flush()
        ready, _, _ = select.select([self.process.stdout], [], [], timeout)
        require(ready, 'native runtime control deadline; whole-process recovery required')
        response = self.process.stdout.readline(16384)  # Responses are fixed diagnostic records, far below this cap.
        require(response.endswith(b'\n'), 'native runtime control response missing or oversized')
        value = json.loads(response)
        if not allow_error:
            require(value.get('result') == 0, f'{text.split()[0]} failed: result={value.get("result")}')
        return value

    def load(self, service):
        permissions = service['permissions']
        path = self.store.materialize(service)
        response = self.command(f'LOAD {str(path).encode().hex()} {service["handles"]} {permissions["timers"]} '
                                f'{permissions["gpio_mask"]} {permissions["publish_mask"]} {permissions["subscribe_mask"]}')
        self.instances[service['name']] = response['instance']
        if service.get('config'):
            self.command(f'CONFIGURE {response["instance"]} {service["config"]}')
        actual = self.command(f'STATUS {response["instance"]}')
        require(all(actual[field] == value for field, value in service['memory'].items()),
                f'{service["name"]}: manifest/native descriptor memory mismatch')

    def launch(self, name):
        instance = self.instances[name]
        self.command(f'START {instance}')
        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline:
            status = self.command(f'STATUS {instance}')
            if status['state'] == 'Running':
                return status
            require(status['state'] not in ('Failed', 'Stopped'), f'{name}: launch failed: {status}')
            time.sleep(POLL_SECONDS)
        raise PackageError(f'{name}: launch deadline')

    def status(self):
        return {'services': {name: self.command(f'STATUS {instance}') for name, instance in sorted(self.instances.items())},
                'resources': self.command('USAGE')}

    def stop(self, name):
        require(name in self.instances, f'{name}: not loaded')
        instance = self.instances[name]
        result = self.command(f'STOP {instance}', allow_error=True)
        require(result['result'] != -8, 'service deadline; whole-runtime recovery required')
        self.command(f'UNLOAD {instance}')
        del self.instances[name]
        return result

    def start(self, name):
        require(name not in self.instances, f'{name}: already loaded')
        service = next((service for service in self.plan['services'] if service['name'] == name), None)
        require(service is not None, f'{name}: not in the admitted enabled graph')
        self.load(service)
        return self.launch(name)

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=CONTROL_TIMEOUT)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self._dispose()
