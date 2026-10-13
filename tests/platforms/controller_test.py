"""Exercise the real shared controller and POSIX store through its public protocol."""
import hashlib
import json
import os
from pathlib import Path
import select
import struct
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from micros_tooling.storage.deployment import encode_graph
from micros_tooling.platforms.embedded.transport import EmbeddedRemote
from micros_tooling.storage.packages import admission_plan, read_package
from tools.packaging.demo_packages import build_demo


class Controller:
    def __init__(self, executable, store):
        self.process = subprocess.Popen([str(executable)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
            env={**os.environ, "MICROS_CONTROLLER_STORE": str(store)})
        self.session = "0123456789abcdef0123456789abcdef"

    def rpc(self, operation, bank=0, slot=0, cursor=0, body=b"", success=True):
        line = f"RPC {operation} {bank} {slot} {cursor} {self.session} {body.hex() or '-'}\n"
        self.process.stdin.write(line.encode())
        self.process.stdin.flush()
        deadline = time.monotonic() + 15
        # Native events are diagnostics, never interpreted as acknowledgements.
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self.process.stdout], [], [], 1)
            if not ready:
                continue
            response = self.process.stdout.readline()
            if not response:
                raise RuntimeError("controller exited")
            if response.startswith(b"{"):
                value = json.loads(response)
                if success:
                    assert value["result"] == 0, value
                return value
        raise TimeoutError("controller response deadline")

    def begin(self):
        selected = self.rpc(0)["activation"]
        self.rpc(8, body=bytes.fromhex(selected["good_sha256"]) + struct.pack("<I", selected["sequence"]))

    def upload(self, bank, slot, data, graph=False):
        operation = 22 if graph else 19
        self.rpc(operation, bank, slot, body=struct.pack("<I", len(data)))
        # Reject out-of-order fragments without advancing the accepted cursor.
        bad = self.rpc(operation + 1, bank, slot, 64, data[:64], success=False)
        assert bad["result"] != 0
        for offset in range(0, len(data), 256):
            self.rpc(operation + 1, bank, slot, offset, data[offset:offset + 256])
        self.rpc(operation + 2, bank, slot)

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process.stdout.close()


class PipeSerial:
    """Exercise the production serial client against an isolated native controller."""
    def __init__(self, controller):
        self.process = controller.process

    def write(self, data):
        self.process.stdin.write(data)
        self.process.stdin.flush()

    def read_until(self, marker, size):
        ready, _, _ = select.select([self.process.stdout], [], [], 1)
        return self.process.stdout.readline(size) if ready else b''


def main():
    build = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="micros-unified-controller-") as directory:
        root = Path(directory)
        build_demo(build, root / "packages")
        packages = [read_package(path.read_bytes()) for path in sorted((root / "packages").glob("*.msp"))]
        plan = admission_plan(packages)
        by_name = {package["manifest"]["name"]: package for package in packages}
        slots = {service["name"]: index for index, service in enumerate(plan["services"])}
        bindings = dict(gpio=[dict(name=f"line{i}", line=i, pin=pin, direction="output")
                             for i, pin in enumerate((2, 4, 5, 16))], recovery_button=None)
        graph = encode_graph(plan, 0, slots, bindings)
        images = [by_name[service["name"]]["image"] for service in plan["services"]]
        digest = hashlib.sha256(graph + b"".join(images)).digest()
        controller = Controller(build / "micros-control", root / "store")
        try:
            controller.begin()
            for slot, image in enumerate(images):
                controller.upload(0, slot, image)
            controller.upload(0, 0, graph, graph=True)
            rejected = controller.rpc(4, body=bytes(32), success=False)
            assert rejected["result"] != 0
            assert controller.rpc(0)["activation"]["good"] == 0xFFFFFFFF
            controller.rpc(4, body=digest)
            controller.rpc(9)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                status = controller.rpc(0)
                if not status["activation"]["pending"]:
                    break
                time.sleep(.05)
            assert status["activation"]["good"] == 0, status
            assert status["activation"]["good_sha256"] == digest.hex()
            assert len(status["services"]) == len(images)
            assert all(service["state"] == "Running" for service in status["services"])
            controller.begin()
            rejected = controller.rpc(19, body=struct.pack("<I", len(images[0])), success=False)
            assert rejected["result"] != 0, "confirmed images must be immutable"
            controller.rpc(9)
            # The same client used for MCU serial deployment must drive the same
            # lifecycle here; service-record order deliberately differs from slots.
            remote = EmbeddedRemote()
            remote.serial = PipeSerial(controller)
            remote.platform, remote.target = status['platform'], status['target']
            remote.session = controller.session
            assert remote.request('COORD INVALID')['reply'].startswith('COORD ERROR')
            alternate_slots = {service['name']: len(images) - 1 - index
                               for index, service in enumerate(plan['services'])}
            alternate_graph = encode_graph(plan, 1, alternate_slots, bindings)
            alternate_digest = hashlib.sha256(alternate_graph + b''.join(images)).hexdigest()
            slot_bytes = max(len(image) for image in images)
            slot_bytes = (slot_bytes + 63) // 64 * 64
            data = bytearray(b'\xff' * (4096 + 4 * slot_bytes))
            data[:len(alternate_graph)] = alternate_graph
            for index, service in enumerate(plan['services']):
                start = 4096 + alternate_slots[service['name']] * slot_bytes
                data[start:start + len(images[index])] = images[index]
            result = remote.deploy(bytes(data), dict(bank=1, bank_bytes=len(data), slot_bytes=slot_bytes,
                base_sha256=status['identity']['base_sha256'], graph_sha256=alternate_digest))
            assert result['good'] == 1 and result['previous'] == 0, result
            remote.request('ROLLBACK')
            remote.end_session()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                result = remote.status()
                if not result['pending']:
                    break
                time.sleep(.05)
            assert result['good'] == 0 and result['good_sha256'] == digest.hex(), result
        finally:
            controller.close()
        # Restart reads the same controller-owned durable selection and boots it.
        controller = Controller(build / "micros-control", root / "store")
        try:
            status = controller.rpc(0)
            assert status["activation"]["good_sha256"] == digest.hex()
            assert len(status["services"]) == len(images)
        finally:
            controller.close()
    print("Unified controller: streamed deployment, fragment ordering, digest rejection, confirmation, protected storage, production client, rollback and restart passed")


if __name__ == "__main__":
    main()
