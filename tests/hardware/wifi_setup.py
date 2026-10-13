#!/usr/bin/env python3
"""Explicit hardware checks for USB provisioning, failed-network rollback and reboot persistence."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from micros_tooling.communication.wifi import Wifi, select_port
from micros_tooling.storage.packages import PackageError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssid", required=True)
    parser.add_argument("--password-file", required=True, type=Path)
    parser.add_argument("--device", default="feather")
    parser.add_argument("--port")
    parser.add_argument("--output", type=Path, default=ROOT / "build/wifi-hardware")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    port = select_port(args.port)

    def save(name, value):
        (args.output / (name + ".json")).write_text(json.dumps(value, indent=2) + "\n")

    def command(label, action, *options, success=True):
        process = subprocess.run(
            [
                str(ROOT / "micros"),
                "wifi",
                action,
                "-d",
                args.device,
                "--port",
                port,
                "--json",
                *map(str, options),
            ],
            capture_output=True,
            text=True,
            timeout=80,
        )
        # Only status/progress is emitted. Never print process arguments containing credential values.
        print(process.stderr, end="", flush=True)
        assert (
            process.returncode == 0
        ) == success, f"{label}: unexpected command outcome"
        if success:
            value = json.loads(process.stdout)
            save(label, value)
            return value
        save(label, dict(exit_code=process.returncode, diagnostic=process.stderr))

    configured = command(
        "configured",
        "setup",
        "--ssid",
        args.ssid,
        "--password-file",
        args.password_file,
    )
    assert configured["saved"] and configured["state"] == "connected"
    # Opening the Feather USB adapter resets it; prove that connection comes from NVS.
    wifi = Wifi(port)
    try:
        deadline = time.monotonic() + 30
        while True:
            restored = wifi.status()
            if restored["state"] == "connected":
                break
            assert (
                time.monotonic() < deadline
            ), "Saved network did not reconnect after reboot"
            time.sleep(0.5)
        assert restored["ssid_hex"] == args.ssid.encode().hex() and restored["saved"]
        save("reboot-persistence", restored)
        networks = wifi.scan()
        assert isinstance(networks, list) and len(networks) <= 12
        save("scan", networks)
        absent = "micros-test-" + uuid.uuid4().hex[:12]
        try:
            wifi.configure(
                absent.encode(), b"", lambda message: print(message, flush=True)
            )
        except PackageError as error:
            save("failed-network", dict(diagnostic=str(error)))
        else:
            raise AssertionError("Unavailable network unexpectedly passed setup")
        # Keep the USB session open: this verifies automatic recovery without a reboot.
        deadline = time.monotonic() + 30
        while True:
            recovered = wifi.status()
            if recovered["state"] == "connected":
                break
            assert time.monotonic() < deadline, "Previous saved network did not recover"
            time.sleep(0.5)
        assert recovered["ssid_hex"] == args.ssid.encode().hex() and recovered["saved"]
        save("previous-network-recovered", recovered)
        # Interrupt another trial with a real reboot before any candidate can be persisted.
        pending = wifi.request("WIFI SET " + absent.encode().hex() + " -")
        assert pending["testing"]
        wifi.device.command("REBOOT", "REBOOTING")
        time.sleep(2)
        deadline = time.monotonic() + 30
        while True:
            status = wifi.status()
            if status["state"] == "connected":
                break
            assert (
                time.monotonic() < deadline
            ), "Interrupted trial changed persistent settings"
            time.sleep(0.5)
        assert (
            status["ssid_hex"] == args.ssid.encode().hex()
            and status["saved"]
            and not status["testing"]
        )
        save("interrupted-trial-reboot", status)
    finally:
        wifi.close()
    print(
        "PASS USB setup, saved Wi-Fi after reboot, network scan, failed trial and reboot during trial."
    )


if __name__ == "__main__":
    main()
