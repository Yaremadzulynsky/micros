#!/usr/bin/env python3
"""Verify the four-service C/C++ graph and repeated teardown on the Feather V2."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from micros_tooling.platforms.esp32.device import Device, prepare
from micros_tooling.storage.packages import build_package
from tools.packaging.demo_packages import manifest

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--port", required=True)
parser.add_argument(
    "--firmware", type=Path, default=Path("build/esp32-runtime/micros_runtime.elf")
)
parser.add_argument("--output", type=Path, default=Path("build/m8-hardware"))
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
image = Path("build/device-cpp/service.mimg").read_bytes()
metadata = json.loads(Path("build/device-cpp/report.json").read_text())
description = manifest("board.cpp", "subscribe", image, b"")
description.update(target=2, channels=[], schemas={}, memory=metadata["memory"])
description["capabilities"] = dict(handles=0, timers=0, gpio=[])
cpp = args.output / "cpp.msp"
cpp.write_bytes(build_package(description, image, {}))
paths = [
    Path("build/device-demo") / (name + ".msp") for name in ("button", "logger", "led")
] + [cpp]


def status(device):
    lines = device.status()
    selection = next(line for line in lines if line.startswith("ACTIVATION "))
    return {
        key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", selection)
    }, lines


def drain(device, seconds):
    deadline = time.monotonic() + seconds
    lines = []
    while time.monotonic() < deadline:
        line = device.line()
        if line:
            lines.append(line)
    return lines


with (args.output / "private-transcript.log").open("w") as log:
    device = Device(args.port, log)
    try:
        drain(
            device, 5
        )  # Allow Wi-Fi/TLS base allocation to settle before teardown measurements.
        device.command("RESUME", "RESUMED")
        record, _ = status(device)
        bank = 0 if record["good"] == 0xFFFFFFFF else 1 - record["good"]
        images, graph, plan = prepare(paths, args.firmware, bank)
        device.upload(images, graph, bank)
        lines = drain(device, 1)
        _, running = status(device)
        assert (
            sum(
                line.startswith("SERVICE ") and "state=Running result=0" in line
                for line in running
            )
            == 4
        ), running
        assert any("LED level=" in line for line in lines) and any(
            "LATENCY_US=" in line for line in lines
        )
        stopped_heaps = []
        for cycle in range(5):
            device.command("STOP", "STOPPED OK")
            _, stopped = status(device)
            summary = next(line for line in stopped if line.startswith("STATUS "))
            assert "services=0" in summary, stopped
            stopped_heaps.append(int(re.search(r" heap=(\d+)", summary)[1]))
            started = device.command(f"BOOT {bank}", "BOOT OK")
            assert any("C++ service initialized" in line for line in started), started
            drain(device, 0.5)
        assert len(set(stopped_heaps[2:])) == 1, stopped_heaps
        device.command("REBOOT", "REBOOTING")
        boot = device.expect("AUTOBOOT OK")
        assert any("C++ service initialized" in line for line in boot), boot
        drain(device, 1)
        record, final = status(device)
        assert record["good"] == bank and not record["pending"], record
        assert (
            sum(
                line.startswith("SERVICE ") and "state=Running result=0" in line
                for line in final
            )
            == 4
        )
    finally:
        device.close()
# Only service/controller evidence is public; Wi-Fi driver startup can print private network names.
raw = (args.output / "private-transcript.log").read_text()
allowed = (
    "C++ ",
    "LED ",
    "LATENCY_US=",
    "SERVICE ",
    "STATUS ",
    "USAGE ",
    "ACTIVATION ",
    "BOOT ",
    "AUTOBOOT ",
    "HEALTH ",
    "STOPPED ",
    "END STATUS",
    "RESUMED",
)
(args.output / "service-transcript.log").write_text(
    "\n".join(line for line in raw.splitlines() if line.startswith(allowed)) + "\n"
)
report = dict(
    cpp_independent_native=True,
    four_running=True,
    cycles=5,
    stopped_heaps=stopped_heaps,
    reboot_reconstructed=True,
    plan=plan,
    running=running,
    final=final,
    firmware_sha256=hashlib.sha256(
        args.firmware.with_suffix(".bin").read_bytes()
    ).hexdigest(),
    cpp_image=metadata,
)
(args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
