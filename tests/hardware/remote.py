#!/usr/bin/env python3
"""Verify actual TLS authorization, remote graph replacement and failed-candidate rollback."""

import argparse
import hashlib
import http.client
import json
from pathlib import Path
import socket
import ssl
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from micros_tooling.communication.remote import Remote
from micros_tooling.storage.packages import PackageError, read_package, build_package

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--host", required=True)
parser.add_argument("--output", type=Path, default=Path("build/m7-hardware"))
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
remote = Remote(
    args.host, "build/private/servercert.pem", "build/private/management.token"
)
firmware = Path("build/esp32-runtime/micros_runtime.elf")
packages = [
    Path("build/device-demo") / (name + ".msp") for name in ("button", "logger", "led")
]
# This suite starts after physical base provisioning/RESUME. All deployment below is Wi-Fi-only.
deadline = time.monotonic() + 30
while True:
    try:
        before = remote.status()
        break
    except (OSError, http.client.HTTPException):
        if time.monotonic() >= deadline:
            raise
        time.sleep(0.25)
if not before["services"]:
    remote.deploy(packages, firmware)
before = remote.status()["activation"]


def unchanged():
    current = remote.status()["activation"]
    assert (current["sequence"], current["good_sha256"]) == (
        before["sequence"],
        before["good_sha256"],
    )


def rejected(method, path, body=b"", token=None, status=None):
    try:
        remote.request(method, path, body, token)
    except PackageError as error:
        if status:
            assert f"({status})" in str(error), error
    else:
        raise AssertionError("request unexpectedly accepted")
    unchanged()


rejected("PUT", "/v1/image?bank=0&slot=0", b"not an image", token="0" * 64, status=401)
rejected("PUT", "/v1/image?bank=0&slot=0", b"x" * 16384, status=413)
rejected("POST", "/v1/activate?bank=0", b"\x00" * 32, status=409)
rejected("PUT", "/v1/firmware", status=404)
# A system trust store must reject this physically pinned self-signed device identity.
connection = http.client.HTTPSConnection(
    args.host, context=ssl.create_default_context(), timeout=10
)
try:
    try:
        connection.request("GET", "/v1/status")
    except ssl.SSLCertVerificationError:
        pass
    else:
        raise AssertionError("unprovisioned TLS peer was trusted")
finally:
    connection.close()
# Disconnect halfway through an authorized upload. The server must never call storage.
sock = remote.context.wrap_socket(
    socket.create_connection((args.host, 443), timeout=10),
    server_hostname="micros.local",
)
header = (
    f'PUT /v1/image?bank={1-before["good"]}&slot=0 HTTP/1.1\r\nHost: micros.local\r\nAuthorization: Bearer {remote.token}\r\nContent-Length: 1024\r\n\r\n'
).encode()
sock.sendall(header + b"x" * 512)
sock.close()
time.sleep(0.2)
unchanged()
# Deploy a faster LED image, with an immutable new package version and unchanged base firmware.
updated = read_package(packages[2].read_bytes())
image = Path("build/device-led-update/service.mimg").read_bytes()
updated["manifest"].update(
    version="1.1.0", image_sha256=hashlib.sha256(image).hexdigest()
)
updated_path = args.output / "led-v1.1.0.msp"
updated_path.write_bytes(build_package(updated["manifest"], image, updated["schemas"]))
result = remote.deploy([*packages[:2], updated_path], firmware)
healthy = remote.status()["activation"]
assert (
    healthy["good"] != before["good"]
    and healthy["good_sha256"] != before["good_sha256"]
)
# A retry of stop is safe and does not consume a boot trial or change selected content.
with remote.deployment_session(remote.status()):
    remote.request("POST", "/v1/stop")
    remote.request("POST", "/v1/stop")
    remote.request(
        "POST",
        f'/v1/activate?bank={healthy["good"]}',
        bytes.fromhex(healthy["good_sha256"]),
    )
assert len(remote.status()["services"]) == 3
# A separately compiled failed-start service must roll back through the exact M6 mechanism.
failed = read_package(packages[0].read_bytes())
image = Path("build/device-failure/service.mimg").read_bytes()
failed["manifest"].update(
    version="1.1.0", image_sha256=hashlib.sha256(image).hexdigest()
)
failed_path = args.output / "button-failed.msp"
failed_path.write_bytes(build_package(failed["manifest"], image, failed["schemas"]))
try:
    remote.deploy([failed_path, packages[1], updated_path], firmware)
except PackageError as error:
    assert "previous healthy graph" in str(error), error
else:
    raise AssertionError("failed candidate unexpectedly confirmed")
final = remote.status()
assert (
    final["activation"]["good"] == healthy["good"]
    and final["activation"]["good_sha256"] == healthy["good_sha256"]
)
assert len(final["services"]) == 3 and all(
    service["state"] == "Running" and service["result"] == 0
    for service in final["services"]
)
log = remote.request("GET", "/v1/logs")
assert "LED level=" in log and "LATENCY_US=" in log
report = {
    "unauthorized_before_mutation": True,
    "oversized_rejected": True,
    "wrong_hash_rejected": True,
    "unprovisioned_tls_rejected": True,
    "interrupted_transfer_preserved_selection": True,
    "firmware_endpoint_absent": True,
    "remote_update_confirmed": True,
    "stop_retry_safe": True,
    "failed_candidate_rolled_back": True,
    "before": before,
    "after_update": healthy,
    "final": final,
}
(args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
(args.output / "service-logs.txt").write_text(log)
print(json.dumps(report, indent=2))
