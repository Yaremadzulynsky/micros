"""Private device profiles and immutable local deployment receipts."""

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import re
from pathlib import Path

from micros_tooling.storage.packages import (
    canonical_json,
    digest,
    identifier,
    read_package,
    require,
)
from micros_tooling.storage.store import atomic_write


class Workspace:
    """Owns local credentials, paired base artifacts, snapshots, and confirmed history."""

    def __init__(self, root):
        self.root = Path(root)

    def read(self, relative, default=None):
        path = self.root / relative
        return json.loads(path.read_text()) if path.exists() else default

    def write(self, relative, value):
        atomic_write(self.root / relative, canonical_json(value))

    @contextmanager
    def locked(self, device=None):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.root / ".lock").open("a+b") as lock:
            device_lock = None
            try:
                fcntl.flock(lock, (fcntl.LOCK_SH if device else fcntl.LOCK_EX) | fcntl.LOCK_NB)
                if device:
                    if not isinstance(device, str) or not re.fullmatch(r"[0-9a-f]{12}", device):
                        identifier(device, "device name")
                    directory = self.root / ".locks"
                    directory.mkdir(exist_ok=True, mode=0o700)
                    device_lock = (directory / device).open("a+b")
                    fcntl.flock(device_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if device_lock:
                    device_lock.close()
                raise ValueError(
                    "Another micros command is modifying this device or its profiles. Status and logs remain available."
                ) from None
            try:
                yield
            finally:
                if device_lock:
                    device_lock.close()
                fcntl.flock(lock, fcntl.LOCK_UN)

    def profiles(self):
        from micros_tooling.config.repository import saved_source

        profiles = self.read("devices.json", dict(default=None, devices={}))
        for profile in profiles["devices"].values():
            for key in ("board_source", "project"):
                if key in profile:
                    profile[key] = saved_source(profile[key])
        return profiles

    def device(self, name=None):
        profiles = self.profiles()
        name = name or profiles["default"]
        if name and name not in profiles["devices"]:
            matches = [key for key, profile in profiles["devices"].items()
                       if profile.get("device_id") == name]
            require(len(matches) <= 1, "Hardware ID matches multiple saved devices; select the saved name.")
            if matches:
                name = matches[0]
        require(
            name in profiles["devices"],
            "No saved device selected. Run ./micros device add --help.",
        )
        return name, profiles["devices"][name]

    def add_device(
        self, name, host, certificate, token, firmware, configuration, transport, board=None
    ):
        identifier(name, "device name")
        profiles = self.profiles()
        require(
            name not in profiles["devices"],
            f"Device {name} already exists. Use device address to change its IP.",
        )
        from micros_tooling.communication.remote import Remote

        Remote(
            host, certificate, token
        )  # Validate credentials without sending them anywhere.
        from micros_tooling.platforms.esp32.build_service import load_symbol_addresses

        symbols = load_symbol_addresses(Path(firmware))
        require(
            all(f"micros_code_slot{slot}" in symbols for slot in range(4)),
            "Base ELF does not export the four runtime slots.",
        )
        directory = self.root / "devices" / name
        if board is not None:
            from micros_tooling.config.resources import load_board, verify_board_firmware
            verify_board_firmware(load_board(board), firmware)
        for filename, source in [
            ("certificate.pem", certificate),
            ("token", token),
            ("firmware.elf", firmware),
        ]:
            atomic_write(directory / filename, Path(source).read_bytes())
        if configuration:
            atomic_write(directory / "sdkconfig", Path(configuration).read_bytes())
        profiles["devices"][name] = dict(
            host=host,
            transport=transport,
            firmware_sha256=digest((directory / "firmware.elf").read_bytes()),
        )
        if board is not None:
            atomic_write(directory / "board.toml", Path(board).read_bytes())
            profiles["devices"][name]["board"] = "board.toml"
        if profiles["default"] is None:
            profiles["default"] = name
        self.write("devices.json", profiles)

    def files(self, name):
        directory = self.root / "devices" / name
        return (
            directory / "certificate.pem",
            directory / "token",
            directory / "firmware.elf",
        )

    def snapshot(self, packages, inspection, firmware):
        from micros_tooling.deployment.preview import details
        blobs = [Path(path).read_bytes() for path in packages]
        package_hashes = [digest(blob) for blob in blobs]
        identity = digest(
            canonical_json(
                dict(
                    packages=package_hashes,
                    firmware=digest(Path(firmware).read_bytes()),
                )
            )
        )
        directory = self.root / "snapshots" / identity
        metadata = dict(
            details=details(packages, firmware),
            resources=inspection.get("plan", {}).get("resources", {}),
            id=identity,
            packages=package_hashes,
            firmware_sha256=digest(Path(firmware).read_bytes()),
            banks={
                str(bank): data["digest"] for bank, data in inspection["banks"].items()
            },
            services=[
                dict(
                    name=read_package(blob)["manifest"]["name"],
                    version=read_package(blob)["manifest"]["version"],
                )
                for blob in blobs
            ],
        )
        for package_hash, blob in zip(package_hashes, blobs):
            atomic_write(directory / (package_hash + ".msp"), blob)
        self.write(Path("snapshots") / identity / "receipt.json", metadata)
        return metadata

    def snapshot_packages(self, receipt, firmware, verify_base=True):
        if verify_base:
            require(receipt["firmware_sha256"] == digest(Path(firmware).read_bytes()),
                    "Snapshot belongs to a different paired base.")
        require(not receipt.get("artifacts_pruned"), "Release packages were pruned; deploy an exported release bundle instead.")
        paths = [
            self.root / "snapshots" / receipt["id"] / (value + ".msp")
            for value in receipt["packages"]
        ]
        for path, expected in zip(paths, receipt["packages"]):
            require(path.is_file(), "Saved release package is missing. Restore a private backup or use an exported release bundle.")
            require(
                digest(path.read_bytes()) == expected,
                "Saved package is damaged; refusing deployment.",
            )
        return paths

    def matching(self, status, name=None):
        activation = status["activation"]
        paths = sorted((self.root / "snapshots").glob("*/receipt.json"))
        try:
            history = self.history(name) if name else []
        except (OSError, ValueError):
            history = []
        if not isinstance(history, list):
            history = []
        history = [event for event in history if isinstance(event, dict)
                   and isinstance(event.get("snapshot"), str) and len(event["snapshot"]) == 64
                   and all(character in "0123456789abcdef" for character in event["snapshot"])]
        if history:
            paths.insert(
                0, self.root / "snapshots" / history[-1]["snapshot"] / "receipt.json"
            )
        for path in paths:
            try:
                receipt = json.loads(path.read_text())
            except (OSError, ValueError):
                continue  # Missing local metadata must not disable live diagnostics.
            if not isinstance(receipt, dict) or not isinstance(receipt.get("banks"), dict):
                continue
            if not isinstance(receipt.get("id"), str) or len(receipt["id"]) != 64 or not all(
                    character in "0123456789abcdef" for character in receipt["id"]) or not isinstance(receipt.get("services"), list):
                continue
            if not all(isinstance(service, dict) and isinstance(service.get("name"), str)
                       and isinstance(service.get("version"), str) for service in receipt["services"]):
                continue
            base = (status.get("identity") or {}).get("base_sha256")
            if base and receipt.get("firmware_sha256") != base:
                continue
            if (
                receipt["banks"].get(str(activation["good"]))
                == activation["good_sha256"]
            ):
                return receipt
        return None

    def history(self, name):
        return self.read(Path("devices") / name / "history.json", [])

    def confirm(self, name, receipt):
        history = self.history(name)
        if not history or history[-1]["snapshot"] != receipt["id"]:
            history.append(
                dict(
                    snapshot=receipt["id"],
                    confirmed_at=datetime.now(timezone.utc).isoformat(),
                )
            )
            self.write(Path("devices") / name / "history.json", history)

    def observe(self, name, status):
        from micros_tooling.deployment.deploy import running

        receipt = self.matching(status, name)
        if (
            receipt
            and not status["activation"]["pending"]
            and running(status, len(receipt["services"]))
        ):
            self.confirm(name, receipt)
        return receipt

    def rollback_target(self, name, status, target=None):
        if target:
            matches = {event["snapshot"] for event in self.history(name)
                       if event["snapshot"].startswith(target)}
            require(len(matches) == 1, "Choose a unique recorded release ID; run micros history.")
            return self.read(Path("snapshots") / matches.pop() / "receipt.json")
        current = self.matching(status, name)
        require(
            current is not None,
            "Current application is not in local history. Deploy it once to record a baseline.",
        )
        history = self.history(name)
        require(
            history and history[-1]["snapshot"] == current["id"],
            "Current application has not been confirmed locally. Run status first.",
        )
        for event in reversed(history[:-1]):
            if event["snapshot"] != current["id"]:
                return self.read(Path("snapshots") / event["snapshot"] / "receipt.json")
        raise ValueError("No previous deployment saved for this device yet.")
