#!/usr/bin/env python3
"""Run the V1 public-CLI demonstration with retained packages, status and logs."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from micros_tooling.storage.packages import build_package, canonical_json, read_package
from micros_tooling.host import daemon
from micros_tooling.storage.store import Store
from tools.packaging.demo_packages import build_demo


def demonstrate(build, output):
    output.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="run-", dir=output))
    store = Store(directory / "store")
    packages = directory / "packages"
    selection = build_demo(build, packages)
    cli = Path(__file__).resolve().parents[1] / "cli/microsctl.py"
    events = []

    def command(*arguments):
        result = subprocess.run(
            [
                sys.executable,
                str(cli),
                "--store",
                str(store.root),
                *map(str, arguments),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return json.loads(result.stdout) if result.stdout else None

    try:
        for name in ("publisher", "fast", "slow"):
            command("install", packages / f"{name}.msp")
        command("configure", packages / "enabled.json")
        events.append({"install_plan": command("plan")})
        command("activate", "--runtime", build / "micros-control")
        deadline = time.monotonic() + 8
        while "slow logger: messages missed" not in command("logs"):
            if time.monotonic() > deadline:
                raise RuntimeError("Expected explicit bounded-stream loss")
            time.sleep(0.1)
        events.append({"run_and_explicit_loss": True})
        command("stop", "demo.slow")
        assert len(command("status")["services"]) == 2
        command("start", "demo.slow")
        command("restart", "demo.fast")
        events.append({"stop_start_restart": True})
        command("shutdown")

        # A genuinely different independently compiled image replaces the logger.
        package = read_package((packages / "fast.msp").read_bytes())
        description = package["manifest"]
        image = (build / "cpp.mimg").read_bytes()
        import hashlib

        description.update(
            version="1.1.0", image_sha256=hashlib.sha256(image).hexdigest()
        )
        description["memory"] = dict(arena_bytes=4, arena_alignment=4, stack_bytes=4096)
        description["capabilities"] = dict(handles=0, timers=0, gpio=[])
        description["channels"], description["schemas"] = [], {}
        update = packages / "cpp-update.msp"
        update.write_bytes(build_package(description, image, {}))
        command("install", update)
        selection["demo.fast"] = "1.1.0"
        selected = directory / "selected.json"
        selected.write_bytes(canonical_json(selection))
        command("configure", selected)
        command("activate", "--runtime", build / "micros-control")
        assert "C++ service initialized" in command("logs")
        events.append({"cpp_update": command("status")})
        command("shutdown")

        image = (build / "fixture_FAIL_START.mimg").read_bytes()
        description.update(
            version="1.2.0", image_sha256=hashlib.sha256(image).hexdigest()
        )
        description["memory"] = dict(
            arena_bytes=24, arena_alignment=8, stack_bytes=4096
        )
        description["capabilities"] = dict(handles=2, timers=1, gpio=[0])
        failed = packages / "failed-update.msp"
        failed.write_bytes(build_package(description, image, {}))
        command("install", failed)
        selection["demo.fast"] = "1.2.0"
        selected.write_bytes(canonical_json(selection))
        command("configure", selected)
        command("activate", "--runtime", build / "micros-control")
        status = command("status")
        assert status["activation"]["good"]["demo.fast"] == "1.1.0", status
        assert all(
            service["state"] == "Running" for service in status["services"].values()
        )
        events.append({"failed_update_rollback": status})
        (directory / "service.log").write_text(command("logs"))
        command("shutdown")
        command("boot", "--runtime", build / "micros-control")
        assert command("status")["activation"]["good"]["demo.fast"] == "1.1.0"
        events.append({"selected_good_reconstructed": True})
    finally:
        if daemon.running(store):
            daemon.request(store, {"action": "shutdown"})
    (directory / "report.json").write_text(json.dumps(events, indent=2) + "\n")
    print(
        f"V1 install/run/loss/stop/restart/C++ update/rollback/reboot passed: {directory}"
    )
    return directory


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("build/host"))
    parser.add_argument("--output", type=Path, default=Path("build/v1-demo"))
    arguments = parser.parse_args()
    demonstrate(arguments.build.resolve(), arguments.output.resolve())
