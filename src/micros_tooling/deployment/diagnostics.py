"""Read-only operator diagnostics, independent of build artifacts and deployment locks."""

from pathlib import Path
import shutil
import ssl
import time

from micros_tooling.deployment.identity import verify_base
from micros_tooling.communication.remote import DockerRemote, Remote


def connect(workspace, name):
    """Construct a verified transport using only the saved address and credentials."""
    name, profile = workspace.device(name)
    from micros_tooling.fleet.server import configured_remote
    identity = profile.get("device_id") or profile.get("mac", "").replace(":", "")
    remote = configured_remote(workspace, identity) if identity else None
    if remote is not None:
        return name, profile, remote
    if profile.get("relay"):
        from micros_tooling.fleet.server import connect_profile
        return name, profile, connect_profile(workspace, name, profile)
    certificate, token, _ = workspace.files(name)
    remote = (DockerRemote if profile["transport"] == "docker" else Remote)(
        profile["host"], certificate, token)
    return name, profile, remote


def doctor(workspace, name):
    """Return independent prerequisite checks; failed checks do not hide later local checks."""
    checks = []

    def check(label, operation):
        try:
            detail = operation()
            checks.append(dict(check=label, okay=True, detail=str(detail)))
            return detail
        except Exception as error:
            checks.append(dict(check=label, okay=False, detail=str(error)))
            return None

    for tool in ("cmake", "ninja", "openssl"):
        def locate(tool=tool):
            path = shutil.which(tool)
            if not path:
                raise ValueError(f"Install {tool}; see docs/archive/documentation/BUILDING.md")
            return path
        check(tool, locate)
    from micros_tooling.platforms.esp32.application import PINNED_COMPILER
    def compiler():
        path = shutil.which("xtensa-esp32-elf-gcc") or str(Path.home() /
            f".espressif/tools/xtensa-esp-elf/{PINNED_COMPILER}/xtensa-esp-elf/bin/xtensa-esp32-elf-gcc")
        if not Path(path).is_file():
            raise ValueError("Install the pinned ESP-IDF toolchain; see docs/archive/documentation/BUILDING.md")
        return path
    check("ESP32 compiler", compiler)
    selected = check("device profile", lambda: workspace.device(name))
    if selected is None:
        return dict(okay=False, checks=checks)
    name, profile = selected
    # Do not serialize credentials or the profile's full contents into diagnostics.
    checks[-1]["detail"] = name + " · " + profile["host"]
    certificate, _, firmware = workspace.files(name)
    def expiry():
        info = ssl._ssl._test_decode_cert(str(certificate))
        days = int((ssl.cert_time_to_seconds(info["notAfter"]) - time.time()) / 86400)
        if days < 30:
            raise ValueError(f"Certificate expires in {days} days. Plan physical identity rotation; see docs/archive/documentation/WIFI.md.")
        return f"Certificate valid for {days} more days"
    check("certificate expiry", expiry)
    connection = check("transport credentials", lambda: connect(workspace, name)[2])
    if connection:
        checks[-1]["detail"] = profile["transport"] + " HTTPS"
        status = check("authenticated status", connection.status)
        if status:
            checks[-1]["detail"] = "Device reachable and authenticated"
            identity = check("base compatibility", lambda: verify_base(status, firmware))
            if identity:
                checks[-1]["detail"] = identity["base_sha256"]
    return dict(device=name, okay=all(item["okay"] for item in checks), checks=checks)


def show_status(name, status, receipt):
    """Explain observed runtime state without claiming application correctness."""
    selection = status["activation"]
    print(f"{name}: " + ("physical recovery" if status.get("physical_recovery") else
          "startup trial pending" if selection["pending"] else
          "running" if status["services"] and all(s["state"] == "Running" and not s["result"]
          for s in status["services"]) else "stopped or failed"))
    print("Application readiness: not reported (runtime liveness only)")
    selected_bank = str(selection["good"]) if selection["good"] in (0, 1) else "none"
    print(f"Selected bank: {selected_bank} · free heap: {status['heap']} bytes")
    if "uptime_us" in status:
        # esp_reset_reason_t order from the pinned ESP-IDF esp_system.h.
        reasons = ("unknown", "power on", "external reset", "software reset", "panic",
                   "interrupt watchdog", "task watchdog", "watchdog", "deep sleep",
                   "brownout", "SDIO", "USB", "JTAG", "efuse error", "power glitch", "CPU lockup")
        code = status["reset_reason"]
        reset = reasons[code] if 0 <= code < len(reasons) else "unknown"
        print(f"Uptime: {status['uptime_us'] // 1000000}s · reset: {reset} ({code})")
    if status.get("deployment_session"):
        print("Update session: " + status["deployment_session"] + " (device-owned expiry)")
    names = receipt["services"] if receipt else []
    for index, service in enumerate(status["services"]):
        label = names[index]["name"] if index < len(names) else f"Unrecorded service {index + 1}"
        # Public ABI result codes; unknown future codes remain visible numerically.
        reasons = {0: "OK", -1: "invalid argument", -2: "capacity", -3: "invalid state",
                   -4: "unsupported", -5: "service failure", -6: "stale handle", -7: "busy",
                   -8: "reboot required", -9: "empty", -10: "messages missed"}
        reason = reasons.get(service["result"], "unknown result")
        print(f"  [{index}] {label}: {service['state']} · {reason} ({service['result']}) · {service['steps']} steps"
              + (f" · stack free {service['stack_free_bytes']} bytes" if "stack_free_bytes" in service else ""))
