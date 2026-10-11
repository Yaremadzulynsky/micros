"""ESP8266 platform commands over the shared embedded protocol."""

import getpass
import json
import time
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from micros_tooling.storage.packages import require
from .transport import SerialRemote
from .build import ROOT, build, base_info


def state_root():
    return Path(os.environ.get("MICROS_STATE_DIR", ROOT / ".micros")) / "esp8266"


def profile_path(name):
    require(
        isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name),
        "Invalid device name",
    )
    return state_root() / "devices" / (name + ".json")


def handles(args):
    name = getattr(args, "device", None)
    return getattr(args, "platform", None) == "esp8266" or bool(
        name and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) and profile_path(name).is_file()
    )


def connect(args, profile):
    if (getattr(args, "via", None) or "usb") == "usb":
        from micros_tooling.platforms.embedded.transport import verify_selected_usb
        return verify_selected_usb(SerialRemote(getattr(args, "port", None), profile.get("serial_number")), profile.get('device_id'))
    from micros_tooling.fleet.server import configured_remote
    from micros_tooling.storage.workspace import Workspace
    from .transport import NetworkRemote
    require(profile.get('device_id'), 'Select an enrolled controller with -d NAME.')
    relay = configured_remote(Workspace(state_root().parent), profile['device_id'])
    require(relay is not None, 'Configure console operator access first.')
    return NetworkRemote(relay)


def main(args):
    name = (
        getattr(args, "name", None) if args.command == "init" else getattr(args, "device", None)
    )
    profile = (
        json.loads(profile_path(name).read_text())
        if name and profile_path(name).is_file()
        else {}
    )
    profile.update(getattr(args, 'enrolled_profile', {}))
    firmware = Path(
        getattr(args, "firmware", None)
        or profile.get("firmware", ROOT / "build/esp8266/firmware/micros_esp8266.elf")
    )
    if args.command == 'history':
        path = state_root() / 'history' / ((name or 'usb') + '.json')
        print(path.read_text() if path.exists() else '[]')
        return
    if args.command == "init" and args.phase in ("plan", "prepare"):
        if args.phase == "prepare":
            if not all(path.exists() for path in (
                ROOT / "build/toolchains/esp8266-rtos-sdk-v3.4",
                ROOT / "build/toolchains/xtensa-lx106-elf/bin/xtensa-lx106-elf-gcc",
                ROOT / "build/esp8266/python/bin/python",
            )):
                from .bootstrap import setup
                setup(ROOT)
            subprocess.run(
                [sys.executable, str(ROOT / "src/micros_tooling/platforms/build_esp8266.py")], check=True
            )
        print(
            json.dumps(
                dict(
                    platform="esp8266",
                    firmware=str(firmware),
                    next="init --phase flash or --phase connect",
                )
            )
        )
        return
    if args.command == "init" and args.phase == "flash":
        from .flash import flash

        flash(firmware, getattr(args, "port", None))
    with connect(args, profile) as remote:
        if args.command == "init":
            status = remote.status()
            require(
                status["base_sha256"] == base_info(firmware)["hash"].hex(),
                "Connected base differs from ELF",
            )
            device_id = status["identity"]["device_id"]
            credentials = getattr(args, "relay_credentials", None)
            if credentials:
                from urllib.parse import urlsplit

                require(credentials.name == device_id, "Enrollment identity differs from board")
                origin = urlsplit(json.loads((credentials / "server.json").read_text())["url"])
                require(
                    origin.scheme == "https"
                    and origin.hostname
                    and origin.path in ("", "/")
                    and not origin.username
                    and not origin.query
                    and not origin.fragment,
                    "Invalid relay URL",
                )
                token = (credentials / "relay.token").read_text().strip()
                require(re.fullmatch("[0-9a-f]{64}", token), "Invalid device token")
                remote.request(f"RELAY_SET {origin.hostname} {origin.port or 443} {token}")
            directory = state_root() / "bases" / status["base_sha256"]
            directory.mkdir(parents=True, exist_ok=True)
            saved = directory / "micros_esp8266.elf"
            for source, dest in (
                (firmware, saved),
                (firmware.with_suffix(".bin"), saved.with_suffix(".bin")),
            ):
                if source.resolve() != dest.resolve():
                    shutil.copyfile(source, dest)
            profile = dict(
                platform="esp8266",
                device_id=device_id,
                serial_number=remote.serial_number,
                firmware=str(saved.resolve()),
            )
            from micros_tooling.storage.store import atomic_write

            atomic_write(profile_path(name), json.dumps(profile, indent=2).encode() + b"\n")
            print(json.dumps(profile, indent=2))
            return
        if args.command == "base-update":
            from .base_ota import update

            result = update(
                remote, firmware, getattr(args, "image", None), getattr(args, "dry_run", False),
                chunked=getattr(args, "chunked", False),
            )
            if result.get("confirmed") and name:
                directory = state_root() / "bases" / result["status"]["base_sha256"]
                directory.mkdir(parents=True, exist_ok=True)
                saved = directory / "micros_esp8266.elf"
                for source, dest in (
                    (firmware, saved),
                    (firmware.with_suffix(".bin"), saved.with_suffix(".bin")),
                ):
                    if source.resolve() != dest.resolve():
                        shutil.copyfile(source, dest)
                profile["firmware"] = str(saved.resolve())
                from micros_tooling.deployment.selection import record_base_update
                record_base_update(args, result, saved)
                from micros_tooling.storage.store import atomic_write

                atomic_write(profile_path(name), json.dumps(profile, indent=2).encode() + b"\n")
        elif args.command == "wifi":
            if args.wifi_action in ("status", "list"):
                result = remote.request("WIFI_GET" if args.wifi_action == "list" else "WIFI")
            else:
                require(
                    args.wifi_action in ("setup", "add"), "Use wifi setup, add, status or list"
                )
                ssid = args.ssid or input("Network name: ")
                password = (
                    ""
                    if args.open_network
                    else (
                        args.password_file.read_text().rstrip("\n")
                        if args.password_file
                        else getpass.getpass("Wi-Fi password: ")
                    )
                )
                require(
                    0 < len(ssid.encode()) <= 32 and "\0" not in ssid + password, "Invalid SSID"
                )
                require(
                    not password
                    or 8 <= len(password.encode()) <= 63
                    or (
                        len(password) == 64
                        and all(c in "0123456789abcdefABCDEF" for c in password)
                    ),
                    "Invalid Wi-Fi password",
                )
                if args.wifi_action == "add" or getattr(args, "fallback", False):
                    networks = remote.request("WIFI_GET")["networks"]
                    primary = next((n for n in networks if not n.get("fallback")), None)
                    require(primary, "Set up the primary network first")
                    command = (
                        "WIFI_PROFILES "
                        + primary["ssid_hex"]
                        + " keep "
                        + ssid.encode().hex()
                        + " "
                        + (password.encode().hex() or "-")
                    )
                else:
                    command = (
                        "WIFI_SET "
                        + ssid.encode().hex()
                        + " "
                        + (password.encode().hex() or "-")
                    )
                remote.request(command)
                result = remote.request("WIFI_GET")
        elif args.command in ("status", "doctor", "logs", "stop", "recover", "rollback", "reboot"):
            expected = None
            if args.command == 'rollback':
                expected = remote.status()['previous']
                require(expected in (0, 1), 'No previous confirmed application is available.')
                if getattr(args, 'dry_run', False):
                    print(json.dumps(dict(previous=expected, dry_run=True)))
                    return
            result = remote.status() if args.command in ('status', 'doctor') else remote.request(args.command.upper())
            if args.command in ('recover', 'rollback'):
                deadline = time.monotonic() + 12
                while True:
                    result = remote.status()
                    running = result['services'] and all(s['state'] in (4, 'Running') for s in result['services'])
                    if not result['pending'] and result['active'] == result['good'] and running:
                        require(expected is None or result['good'] == expected, 'Rollback did not select the expected application.')
                        break
                    require(time.monotonic() < deadline, 'Application has not confirmed; inspect status before retrying.')
                    time.sleep(.15)
            if args.command == 'logs':
                result = dict(text=bytes.fromhex(result['hex']).decode('utf-8', errors='replace'))
        elif args.command in ("build", "deploy"):
            compiler = Path(
                getattr(args, "compiler_dir", None)
                or ROOT / "build/toolchains/xtensa-lx106-elf/bin"
            )
            project = getattr(args, "project", None)
            if project is None or project == ROOT / "config/micros.toml":
                project = ROOT / "examples/esp8266-demo/micros.toml"
            status = remote.status()
            require(
                status["base_sha256"] == base_info(firmware)["hash"].hex(),
                "Connected base differs from ELF",
            )
            bank = 1 - status["good"] if status["good"] < 2 else 0
            output = Path(getattr(args, "output", None) or ROOT / "build/esp8266/deploy")
            if args.command == 'deploy' and not getattr(args, 'force', False) and status['good'] in (0, 1) and not status['pending'] and status['active'] == status['good']:
                current = build(project, firmware, output / 'current-check', compiler, status['good'], getattr(args, 'board', None), getattr(args, 'overlay', None))
                if current['graph_sha256'] == status['good_sha256'] and all(s['state'] in (4, 'Running') for s in status['services']):
                    print(json.dumps(dict(unchanged=True, message='Application already matches; no flash writes or restart.', status=status)))
                    return
            report = build(
                project,
                firmware,
                output,
                compiler,
                bank,
                getattr(args, "board", None),
                getattr(args, "overlay", None),
            )
            result = (
                report
                if args.command == "build" or getattr(args, "dry_run", False)
                else remote.deploy((output / "bank.bin").read_bytes(), report)
            )
            if args.command == 'deploy' and not getattr(args, 'dry_run', False):
                path = state_root() / 'history' / ((name or 'usb') + '.json')
                history = json.loads(path.read_text()) if path.exists() else []
                history.append(dict(time=time.time(), report=report, status=result))
                from micros_tooling.storage.store import atomic_write
                atomic_write(path, json.dumps(history, indent=2).encode() + b'\n')
        else:
            raise ValueError("ESP8266 command is not implemented: " + args.command)
        print(json.dumps(result, indent=2))
