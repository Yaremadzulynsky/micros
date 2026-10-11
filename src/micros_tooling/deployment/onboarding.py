"""Resumable physical provisioning with a private pre-flash backup."""

import json
import os
import re
from pathlib import Path
import subprocess
import sys

from micros_tooling.platforms.esp32.application import build_application, ROOT
from micros_tooling.config.configuration import load_project, read_toml, unit_identity
from micros_tooling.deployment.identity import verify_base
from micros_tooling.storage.packages import PackageError, digest, identifier, require
from micros_tooling.deployment.provision import provision
from micros_tooling.communication.remote import Remote, DockerRemote
from micros_tooling.storage.store import atomic_write


def onboard(workspace, args, progress):
    """Prepare locally, flash explicitly, then connect; each phase can be retried."""
    identifier(args.name, "device name")
    directory = workspace.root / "onboarding" / args.name
    build = directory / "base"
    credentials = args.credentials or directory / "credentials"
    firmware = build / "micros_runtime.elf"
    state_path = directory / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    if args.phase == "plan":
        return dict(device=args.name, phases=["prepare: build base and validate application locally",
            "flash: verify capacity, back up complete flash, then replace base over USB",
            "connect: configure Wi-Fi if needed, verify identity, save pairing"],
            directory=str(directory), next=f"./micros init {args.name} --phase prepare")

    def save():
        atomic_write(state_path, json.dumps(state, indent=2).encode())

    def run(command, cwd=None):
        sdk_export = ROOT / "build/toolchains/esp-idf-v5.5.2/export.sh"
        require(sdk_export.is_file(), "ESP32 SDK missing. Run ./micros setup --esp32.")
        # Only fixed shell code is used; paths and command arguments are separate
        # positional parameters, so spaces and shell metacharacters stay literal.
        command = ["bash", "-c", 'source "$1" >/dev/null 2>&1 || exit; shift; exec "$@"',
                   "micros-sdk", str(sdk_export), *command]
        log = directory / "last-command.log"
        atomic_write(log, b"")
        with log.open("wb") as output:
            result = subprocess.run(command, cwd=cwd, stdout=output, stderr=subprocess.STDOUT)
        require(result.returncode == 0,
                f"Onboarding command failed. See {directory / 'last-command.log'}; repeat this phase after fixing it.")
        return log.read_text(errors="replace")

    if args.phase == "prepare":
        from micros_tooling.config.resources import select_board
        selected_board = getattr(args, "board", None)
        saved_profile = workspace.profiles()["devices"].get(args.name, {})
        if selected_board is None and "board" not in read_toml(args.project) and saved_profile.get("board"):
            selected_board = workspace.root / "devices" / args.name / "board.toml"
        selected_board = select_board(args.project, selected_board)
        require(selected_board is not None, "Select --board PATH for base preparation")
        board_file = directory / "board.toml"
        atomic_write(board_file, selected_board.read_bytes())
        if getattr(args, "rotate_identity", False):
            import uuid
            require(not args.credentials, "Choose either existing credentials or --rotate-identity.")
            credentials = directory / ("credentials-" + uuid.uuid4().hex)
        provision(credentials)
        build.mkdir(parents=True, exist_ok=True)
        # The application already declares base requirements. Apply them to this
        # isolated build, never the developer's other firmware directory.
        recipe = load_project(args.project, board=board_file)
        settings = recipe.get("required_sdkconfig", {})
        config = build / "sdkconfig"
        existing = config.read_text().splitlines() if config.exists() else []
        existing = [line for line in existing if line.split("=", 1)[0] not in settings
                    and not any(line == f"# {key} is not set" for key in settings)]
        existing += [f"{key}={value}" if value is not None else f"# {key} is not set"
                     for key, value in settings.items()]
        atomic_write(config, ("\n".join(existing) + "\n").encode())
        progress("prepare", "Building a private base with the pinned ESP-IDF environment")
        relay_options = []
        if getattr(args, "relay_credentials", None):
            relay_options = ["--relay-credentials", str(args.relay_credentials.resolve())]
        run([sys.executable, str(ROOT / "src/micros_tooling/platforms/esp32/build_network.py"),
             "--credentials", str(credentials), "--build", str(build), "--project", str(args.project.resolve()),
             "--board", str(board_file.resolve()), *relay_options])
        # A resident management base is useful before any application is selected.
        if recipe["services"]:
            packages = build_application(args.project, firmware, directory / "application", progress, board=board_file)
            from micros_tooling.platforms.esp32.device import prepare
            prepare(packages, firmware, 0)
        from micros_tooling.fleet.server import configured_remote
        artifact_remote = getattr(args, "artifact_remote", None) or configured_remote(workspace)
        if artifact_remote is not None:
            from micros_tooling.storage.artifacts import publish_base
            publish_base(artifact_remote, firmware)
            progress("artifacts", "Published exact base ELF and sdkconfig to the server")
        state.update(unit_device_id=unit_identity(args.project), base_sha256=digest(firmware.read_bytes()), credentials=str(credentials.resolve()),
                     board_source=str(selected_board.resolve()),
                     board_sha256=digest(board_file.read_bytes()))
        flash_files = json.loads((build / "flasher_args.json").read_text())["flash_files"]
        state["flash_files"] = {name: digest((build / name).read_bytes())
                                for name in [*flash_files.values(), "flash_args"]}
        save()
        return dict(device=args.name, phase="prepared", base_sha256=state["base_sha256"],
                    next=f"./micros init {args.name} --phase flash --port PORT")

    require(state.get("base_sha256") == digest(firmware.read_bytes()),
            "Prepared base changed. Repeat init --phase prepare before proceeding.")
    if state.get("board_sha256"):
        require(digest((directory / "board.toml").read_bytes()) == state["board_sha256"],
                "Prepared board definition changed. Repeat init --phase prepare.")
    credentials = Path(state["credentials"])
    from micros_tooling.communication.wifi import Wifi, select_port, setup_from_terminal
    port = select_port(args.port)
    if args.phase == "flash":
        require(args.port, "Flashing requires explicit --port PORT to identify the physical board.")
        require(state.get("flash_files"), "Repeat prepare to record the exact flash artifacts.")
        for name, expected_hash in state["flash_files"].items():
            require(digest((build / name).read_bytes()) == expected_hash,
                    "Prepared flash artifact changed: " + name + ". Repeat prepare.")
        information = run(["python", "-m", "esptool", "--chip", "esp32", "--port", port, "flash_id"])
        from micros_tooling.config.resources import load_board
        flash_mb = load_board(directory / "board.toml").get("flash_mb", 8) if state.get("board_sha256") else 8
        require(re.search(rf"Detected flash size:\s*{flash_mb}MB\b", information),
                "Detected flash capacity does not match the prepared board profile; refusing flash")
        flash_bytes = flash_mb * 1024 * 1024
        found = re.findall(r"MAC:\s*([0-9a-fA-F:]{17})", information)
        require(found, "Cannot verify board MAC; refusing flash")
        board_mac = found[-1].lower().replace(":", "")
        require(not state.get("unit_device_id") or state["unit_device_id"] == board_mac,
                "USB board does not match the prepared unit configuration; refusing flash")
        saved_profile = workspace.profiles()["devices"].get(args.name, {})
        expected = state.get("board_mac") or saved_profile.get("device_id") or saved_profile.get("mac")
        require(not expected or expected.lower().replace(":", "") == board_mac,
                "USB board does not match this onboarding session/profile; refusing flash")
        state["board_mac"] = board_mac
        save()
        backup = directory / "before-flash.bin"
        if not backup.exists():
            progress("backup", f"Saving the complete {flash_mb} MiB flash privately before replacing the base")
            temporary = backup.with_suffix(".partial")
            # Some USB adapters corrupt long reads at high baud. A read failure
            # has not changed flash, so retry conservatively before any write.
            for baud in (230400, 115200):
                progress("backup", f"Reading flash at {baud} baud; progress: {directory / 'last-command.log'}")
                try:
                    run(["python", "-m", "esptool", "--chip", "esp32", "--port", port, "--baud", str(baud),
                         "read_flash", "0", hex(flash_bytes), str(temporary)])
                    break
                except PackageError:
                    if baud == 115200:
                        raise
            require(temporary.stat().st_size == flash_bytes, "Incomplete flash backup; refusing flash")
            temporary.chmod(0o600)
            temporary.replace(backup)
        require(backup.stat().st_size == flash_bytes, "Flash backup is incomplete")
        backup_hash = digest(backup.read_bytes())
        require(not state.get("backup_sha256") or state["backup_sha256"] == backup_hash,
                "Saved flash backup is damaged; refusing flash")
        state["backup_sha256"] = backup_hash
        save()
        progress("flash", "Flashing the prepared base over USB; service history remains base-specific")
        # Flash the reviewed bytes directly. `idf.py flash` can rebuild changed
        # sources, invalidating the prepared identity just before writing.
        run(["python", "-m", "esptool", "--chip", "esp32", "--port", port, "--baud", "115200",
             "--before", "default_reset", "--after", "hard_reset", "write_flash", "@flash_args"], cwd=build)
        state.update(flashed_sha256=state["base_sha256"], port=port)
        save()
        return dict(device=args.name, phase="flashed", backup=str(backup),
                    next=f"./micros init {args.name} --phase connect --port {port}")

    wifi = Wifi(port)
    try:
        progress("wifi", "Waiting for saved Wi-Fi and DHCP after USB reset (up to 90 seconds)")
        status = wifi.settled_status(timeout=90)
        require(status["state"] not in ("connecting", "waiting_for_ip"),
                "Saved Wi-Fi is still connecting. Repeat init --phase connect after DHCP completes; credentials were not changed.")
        if status["state"] != "connected" or args.ssid:
            status = setup_from_terminal(wifi, args, lambda message: progress("wifi", message))
        # Physical controller ownership is explicit in this USB onboarding phase.
        wifi.device.command("RESUME", "RESUMED")
    finally:
        wifi.close()
    host = status["ip"]
    remote = (DockerRemote if args.transport == "docker" else Remote)(
        host, credentials / "servercert.pem", credentials / "management.token")
    identity = verify_base(remote.status(), firmware)
    require(not state.get("board_mac") or state["board_mac"] == identity["device_id"],
            "Connected device does not match the flashed board")
    require(not state.get("unit_device_id") or state["unit_device_id"] == identity["device_id"],
            "Connected device does not match the prepared unit configuration")
    profiles = workspace.profiles()
    previous_base = profiles["devices"].get(args.name, {}).get("firmware_sha256")
    previous_application = profiles["devices"].get(args.name, {}).get("application")
    if args.name in profiles["devices"]:
        old = profiles["devices"][args.name]
        require(not old.get("device_id") or old["device_id"] == identity["device_id"],
                "This board is not the saved device; choose a new profile name.")
        # Archive the complete prior pairing before replacement; never reinterpret
        # old history as releases for the new base.
        import shutil
        source = workspace.root / "devices" / args.name
        archive = directory / ("previous-pairing-" + old["firmware_sha256"])
        if not archive.exists():
            shutil.copytree(source, archive)
        del profiles["devices"][args.name]
        workspace.write("devices.json", profiles)
    workspace.add_device(args.name, host, credentials / "servercert.pem",
                         credentials / "management.token", firmware, build / "sdkconfig", args.transport,
                         directory / "board.toml" if state.get("board_sha256") else None)
    if previous_base != state["base_sha256"]:
        workspace.write(Path("devices") / args.name / "history.json", [])
    profiles = workspace.profiles()
    profiles["devices"][args.name].update(device_id=identity["device_id"], mac=status["mac"], serial_port=port)
    if state.get("board_source"):
        profiles["devices"][args.name]["board_source"] = state["board_source"]
    if previous_application:
        profiles["devices"][args.name]["application"] = previous_application
    workspace.write("devices.json", profiles)
    state["connected"] = identity["device_id"]
    save()
    return dict(device=args.name, phase="paired", identity=identity,
                next=f"./micros deploy -d {args.name}")
