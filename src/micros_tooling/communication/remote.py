"""Certificate-verified, authenticated remote service deployment client."""

import http.client
import json
from pathlib import Path
import ssl
import struct
import uuid
from contextlib import contextmanager
from micros_tooling.storage.packages import PackageError, require

RESPONSE_LIMIT = 16384  # Four service statuses or a bounded device log tail.


class RemoteRejected(PackageError):
    """An HTTP rejection with a stable operator/automation category."""

    def __init__(self, status, payload):
        super().__init__(f"remote request rejected ({status}): " + payload.decode(errors="replace"))
        self.status = status
        self.code = {401: "authorization_rejected", 409: "state_conflict",
                     413: "request_too_large", 503: "device_busy", 504: "outcome_unknown"}.get(status, "protocol_rejected")
        self.retryable = status == 503
        if status == 504:
            self.outcome = "unknown"


def accepted(status, payload):
    if status != 200:
        raise RemoteRejected(status, payload)


def decode_response(payload):
    """Report malformed replies as protocol failures eligible for deployment recovery."""
    try:
        result = json.loads(payload)
    except (ValueError, UnicodeError) as error:
        raise PackageError("Device returned an invalid JSON response.") from error
    require(isinstance(result, dict), "Device returned an invalid management response.")
    return result


class Remote:
    """One physically provisioned device identity; no plaintext fallback or firmware-write API."""

    def __init__(self, host, certificate, token_file, port=443):
        self.host, self.port = host, port
        self.session_id = ""
        self.context = ssl.create_default_context(cafile=str(certificate))
        # The self-signed device certificate is the sole trust anchor. DHCP
        # changes its IP, so verify that exact identity without requiring IP SANs.
        self.context.check_hostname = False
        self.token = Path(token_file).read_text().strip()
        require(
            len(self.token) == 64
            and all(character in "0123456789abcdef" for character in self.token),
            "invalid token file",
        )

    def request(self, method, path, body=b"", token=None):
        connection = http.client.HTTPSConnection(
            self.host, self.port, context=self.context, timeout=20
        )
        try:
            connection.request(
                method,
                path,
                body=body,
                headers={
                    "Authorization": "Bearer "
                    + (self.token if token is None else token),
                    "Content-Type": "application/octet-stream",
                    **({"X-Micros-Session": self.session_id} if self.session_id else {}),
                },
            )
            response = connection.getresponse()
            payload = response.read(RESPONSE_LIMIT + 1)
            require(len(payload) <= RESPONSE_LIMIT, "oversized management response")
            accepted(response.status, payload)
            if path == "/v1/logs":
                return payload.decode(errors="replace")
            return decode_response(payload)
        finally:
            connection.close()

    def status(self):
        status = self.request("GET", "/v1/status")
        try:
            if "identity" in status:
                identity = status["identity"]
                require(isinstance(identity, dict), "Invalid device identity response.")
                for key, length in (("base_sha256", 64), ("device_id", 12)):
                    value = identity.get(key)
                    require(isinstance(value, str) and len(value) == length
                            and all(character in "0123456789abcdef" for character in value),
                            "Invalid device identity: " + key)
            activation = status["activation"]
            require(
                all(
                    type(activation[key]) is int
                    for key in (
                        "sequence",
                        "good",
                        "previous",
                        "candidate",
                        "attempts",
                        "pending",
                    )
                ),
                "Invalid device activation record.",
            )
            require(
                activation["pending"] in (0, 1)
                and activation["good"] in (0, 1, 0xFFFFFFFF),
                "Invalid device bank selection.",
            )
            identity = activation["good_sha256"]
            require(
                isinstance(identity, str)
                and len(identity) == 64
                and all(character in "0123456789abcdef" for character in identity),
                "Invalid device graph identity.",
            )
            require(
                isinstance(status["services"], list) and len(status["services"]) <= 4,
                "Invalid device service list.",
            )
            for service in status["services"]:
                require(
                    isinstance(service["state"], str)
                    and all(
                        type(service[key]) is int
                        for key in ("result", "steps", "callbacks")
                    ),
                    "Invalid device service status.",
                )
            require(type(status["heap"]) is int, "Invalid device memory status.")
        except (KeyError, TypeError) as error:
            raise PackageError(
                "Device returned an incomplete status response."
            ) from error
        return status

    @contextmanager
    def deployment_session(self, before):
        """Reserve the expected selection; the board restores abandoned staging on expiry."""
        require(not self.session_id, "A deployment session is already active on this client.")
        self.session_id = uuid.uuid4().hex
        acquired = False
        try:
            selected = before["activation"]
            self.request("POST", "/v1/session", bytes.fromhex(selected["good_sha256"])
                         + struct.pack("<I", selected["sequence"]))
            acquired = True
            yield
        finally:
            if acquired:
                try:
                    self.request("DELETE", "/v1/session")
                except (OSError, http.client.HTTPException, PackageError):
                    pass  # Expiry is device-owned; never hide the original deployment outcome.
            self.session_id = ""

    def deploy(self, packages, firmware, **options):
        from micros_tooling.deployment.deploy import deploy

        return deploy(self, packages, firmware, **options)


class DockerRemote(Remote):
    """Explicit local Docker transport for hosts whose native LAN route is unavailable."""

    def __init__(self, host, certificate, token_file, port=443):
        super().__init__(host, certificate, token_file, port)
        self.certificate = Path(certificate).read_text()

    def request(self, method, path, body=b"", token=None):
        import base64
        import subprocess

        worker = Path(__file__).with_name("transport_worker.py").read_text()
        try:
            process = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-i",
                    "--pull=never",
                    "--network=host",
                    "micros-linux-tools:v1",
                    "python3",
                    "-c",
                    worker,
                ],
                input=json.dumps(
                    dict(
                        host=self.host,
                        port=self.port,
                        certificate=self.certificate,
                        token=self.token if token is None else token,
                        method=method,
                        path=path,
                        body=base64.b64encode(body).decode(),
                        session=self.session_id,
                    )
                ),
                text=True,
                capture_output=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as error:
            raise OSError(
                "Docker transport timed out; check Docker and device connectivity."
            ) from error
        require(
            process.returncode == 0,
            "Docker transport unavailable. Start Docker and build micros-linux-tools:v1 (docs/archive/documentation/DEPLOYING.md).",
        )
        response = json.loads(process.stdout)
        if "error" in response:
            raise OSError(response["error"])
        payload = base64.b64decode(response["body"])
        require(len(payload) <= RESPONSE_LIMIT, "oversized management response")
        accepted(response["status"], payload)
        return (
            payload.decode(errors="replace")
            if path == "/v1/logs"
            else decode_response(payload)
        )
