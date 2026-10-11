"""Read/write declared bridge ports through the existing authenticated relay."""
import argparse
import os
from pathlib import Path

from micros_tooling.config.configuration import load_project
from micros_tooling.storage.packages import PackageError

ROOT = Path(__file__).resolve().parents[3]


class ChannelMissed(RuntimeError):
    """The bounded stream overwrote unread messages; the next read resumes it."""


class Channels:
    def __init__(self, remote, project):
        self.remote = remote
        services = load_project(project)["services"]
        bridge = next((s for s in services if s["_interface"]["name"] == "bridge"), None)
        if bridge is None:
            raise ValueError("Recipe must enable a service with alias 'bridge'")
        # The device starts subscription-only services first, then publishers,
        # sorting names within each group. IPC addresses this runtime order.
        ordered = sorted(services, key=lambda s: (
            any(p["access"] == "publish" for p in s["_interface"]["ports"]), s["name"]))
        self.instance = ordered.index(bridge)
        self.ports = {p["name"]: p for p in bridge["_interface"]["ports"]}

    def _port(self, name, access):
        port = self.ports.get(name)
        if port is None or port["access"] != access:
            raise ValueError(f"Port {name!r} is not a bridge {access} port")
        return port

    def _rpc(self, command):
        # Resident management caps platform commands at 255 bytes. Never split
        # protobuf messages or retry an operation whose outcome is unknown.
        if len(command) > 255:
            raise ValueError("Message exceeds the relay's 255-byte command limit")
        reply = self.remote.request("POST", "/v1/platform-command", command.encode())["reply"]
        if reply == "IPC ERROR -10":
            raise ChannelMissed("Unread channel messages were overwritten; read again to resume")
        if reply.startswith("IPC ERROR "):
            raise RuntimeError(reply)
        return reply

    def write(self, name, payload):
        port = self._port(name, "publish")
        if not payload or len(payload) > port["max_payload"]:
            raise ValueError("Payload must be nonempty and fit the channel's max_payload")
        key = port["key"]
        reply = self._rpc(f"IPC WRITE {self.instance} {key} {payload.hex()}")
        if reply != f"IPC QUEUED {key}":
            raise RuntimeError("Unexpected IPC write acknowledgement")

    def read(self, name):
        port = self._port(name, "subscribe")
        key = port["key"]
        reply = self._rpc(f"IPC READ {self.instance} {key}")
        if reply == f"IPC EMPTY {key}":
            return None
        prefix = f"IPC DATA {key} "
        if not reply.startswith(prefix):
            raise RuntimeError("Unexpected IPC read acknowledgement")
        payload = bytes.fromhex(reply[len(prefix):])
        if len(payload) > min(port["max_payload"], 256):
            raise RuntimeError("IPC reply exceeds the transport or channel capacity")
        return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--project", type=Path, required=True, help="The deployed TOML recipe")
    parser.add_argument("operation", choices=("read", "write"))
    parser.add_argument("port", help="Port name in services.bridge")
    parser.add_argument("payload", nargs="?", help="Protobuf bytes as hex (write only)")
    args = parser.parse_args()
    from micros_tooling.fleet.server import configured_remote
    from micros_tooling.storage.workspace import Workspace
    try:
        remote = configured_remote(Workspace(Path(os.environ.get("MICROS_STATE_DIR", ROOT / ".micros"))), args.device)
        if remote is None:
            raise ValueError("No configured micros server")
        channels = Channels(remote, args.project)
        if args.operation == "write":
            if args.payload is None:
                raise ValueError("write requires a hex payload")
            channels.write(args.port, bytes.fromhex(args.payload))
            print("queued")
        else:
            if args.payload is not None:
                raise ValueError("read takes no payload")
            result = channels.read(args.port)
            print("empty" if result is None else result.hex())
    except (ValueError, RuntimeError, PackageError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
