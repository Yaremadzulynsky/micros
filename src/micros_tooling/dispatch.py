from micros_tooling.platforms.registry import hardware_names
#!/usr/bin/env python3
"""Friendly terminal client for building, deploying and recovering micros applications."""

import argparse
import http.client
import json
import os
from pathlib import Path
import ssl
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROJECT = None
from micros_tooling.platforms.esp32.application import build_application
from micros_tooling.deployment.deploy import NO_BANK, deploy, inspect_deployment, running
from micros_tooling.storage.packages import digest, require
from micros_tooling.communication.remote import DockerRemote, Remote
from micros_tooling.storage.workspace import Workspace


class CommandParser(argparse.ArgumentParser):
    """Keep usage failures machine-readable when JSON output was requested."""

    def error(self, message):
        if "--json" in sys.argv:
            print(json.dumps(dict(error=dict(code="usage", message=message,
                outcome="not_started", next_action="Run micros --help."))), file=sys.stderr)
            self.exit(2)
        super().error(message)


def parser():
    command = CommandParser(
        prog="micros",
        description=__doc__,
        epilog="Install dependencies: ./micros setup. Guided board setup: ./micros enroll. Diagnose: ./micros doctor.",
    )
    commands = command.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("setup", help="prepare the selected checkout's Python environment")
    setup.add_argument("--esp32", action="store_true", help="also install the pinned ESP32 SDK")
    from micros_tooling.deployment.enrollment import add_parser as enrollment_parser
    enrollment_parser(commands)
    from micros_tooling.deployment.erasure import add_parser as erasure_parser
    erasure_parser(commands)
    from micros_tooling.communication.discovery import add_parser as discovery_parser
    discovery_parser(commands)
    new = commands.add_parser("new", help="create an independent application project offline")
    new.add_argument("directory", type=Path, help="new application directory; must not exist")
    new.add_argument("--platform", choices=hardware_names(), default="esp32",
                     help="accepted for compatibility; enrollment detects the board and selects its profile and memory budget")
    compose = commands.add_parser("compose", help="validate and inspect a setup or deployment offline; optionally emit complete unit recipes")
    compose.add_argument("deployment", type=Path, help="physical setup or deployment TOML naming devices, services, connections and captures")
    compose.add_argument("--output", type=Path, help="write validated recipes to a new review directory")
    compose.add_argument("--json", action="store_true", help="show the complete resolved composition as JSON")
    pins = commands.add_parser("pins", help="list verified chip capabilities and board connections offline")
    pins.add_argument("--profile", required=True, help="board profile, e.g. adafruit_feather_esp32_v2")
    pin_view = pins.add_mutually_exclusive_group()
    pin_view.add_argument("--json", action="store_true")
    pin_view.add_argument("--all", action="store_true", help="show the complete capability table")
    pin_view.add_argument("--pin", type=int, help="explain one GPIO")
    service_scaffold = commands.add_parser("scaffold-service", help="create application hooks and state once")
    service_scaffold.add_argument("--preview", action="store_true", help="print current hook stubs without writing files")
    service_scaffold.add_argument('--new', action='store_true', help='create a new service directory with a minimal declaration and hook sources')
    service_scaffold.add_argument('--example', choices=['counter'], help='create a working example in a new directory (implies --new)')
    service_scaffold.add_argument("contract", type=Path, help="service directory or service.toml")
    service_scaffold.add_argument('--base', help='compare hooks with this Git revision; requires --preview')
    service_scaffold.add_argument('--json', action='store_true')
    contract_diff = commands.add_parser('contract-diff', help='review semantic declaration changes against Git')
    contract_diff.add_argument('declaration', type=Path, help='service directory, service.toml or unit TOML')
    contract_diff.add_argument('--base', required=True, help='Git revision to compare against')
    contract_diff.add_argument('--json', action='store_true')
    contract_diff.add_argument('--stubs', action='store_true', help='show only new/changed hook stubs')
    scaffold = commands.add_parser("scaffold-commands", help="create user-owned command handler stubs once")
    scaffold.add_argument("contract", type=Path)
    scaffold.add_argument("--output", type=Path, required=True)
    commands.add_parser("host", help="build and manage a local native application", add_help=False)
    commands.add_parser("shell", help="interactive device inspection and deployed service commands", add_help=False)
    commands.add_parser("server", help="Docker management server, device registry and relay operations", add_help=False)
    commands.add_parser("devices", help="list devices and availability reported by the management server", add_help=False)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--via", choices=["usb", "relay"], default=None, help="embedded platform management transport")
    common.add_argument("--platform", choices=hardware_names(), help="select the target hardware platform")
    common.add_argument("--compiler-dir", type=Path, help="platform cross-compiler bin directory")
    common.add_argument("-d", "--device", help="server device name/ID, or saved device when no server is configured")
    common.add_argument(
        "--json",
        action="store_true",
        help="machine-readable result; progress goes to stderr",
    )
    base = commands.add_parser("base-update", parents=[common], help="update only the base through A/B OTA")
    base.add_argument("--firmware", type=Path, required=True, help="target OTA-capable base ELF")
    base.add_argument("--port", help="USB serial interface for the selected controller")
    base.add_argument("--image", type=Path, help="matching BIN; defaults to the ELF's sibling")
    base.add_argument("--dry-run", action="store_true", help="validate without writing to the board")
    base.add_argument("--chunked", action="store_true", help="ESP8266: upload bounded chunks through relay instead of board download")
    for name in (
        "config",
        "generate",
        "build",
        "deploy",
        "plan",
        "rollback",
        "status",
        "logs",
        "recover",
        "restart",
        "history",
        "doctor",
        "stop",
        "reboot",
    ):
        child = commands.add_parser(
            name,
            parents=[common],
            help={
                "config": "show resolved service settings without a device",
                "generate": "generate configuration and IPC interfaces for builds and IntelliSense",
                "build": "build packages locally without contacting the device",
                "deploy": "build and deploy the application",
                "plan": "preview an ESP32 application transition without changing the board",
                "rollback": "restore the previous confirmed application",
                "status": "show runtime status and known application",
                "logs": "read the recent device log",
                "recover": "restart the selected good application",
                "restart": "restart one service, preserving peers and channels",
                "history": "list confirmed deployments",
                "doctor": "diagnose local tools, connection, certificate and base compatibility",
                "stop": "intentionally pause the whole application until recover or reboot",
                "reboot": "restart the whole device",
            }[name],
        )
        if name == "generate":
            child.add_argument("--service", type=Path, help="generate a service contract independently of any board")
            child.add_argument("--output", type=Path, help="directory for standalone service interfaces")
        if name == "restart":
            child.add_argument("service_index", type=int, help="zero-based index from status")
        if name == "plan":
            child.set_defaults(command="deploy", dry_run=True, planning=True)
            name = "deploy"
        child.add_argument("--port", help="USB port for an explicitly selected platform")
        if name in ("build", "deploy"):
            child.add_argument("--bank", type=int, choices=[0, 1], help="offline platform build bank")
        if name in ("config", "generate", "build", "deploy"):
            child.add_argument("--project", type=Path, default=None if name in ("build", "deploy") else DEFAULT_PROJECT)
            child.add_argument("--board", type=Path, help="application wiring; defaults to embedded, saved, or adjacent board definition")
            if name != "generate":
                child.add_argument(
                    "--overlay", type=Path, help="TOML file overriding service settings"
                )
        if name == "build":
            child.add_argument("--bundle", type=Path, help="export an immutable reviewed release without deploying")
            child.add_argument(
                "--firmware",
                type=Path,
                help="build against an explicit base ELF without changing device pairing",
            )
            child.add_argument(
                "--output",
                type=Path,
                help="package output for --firmware review builds",
            )
        if name in ("build", "deploy"):
            child.add_argument("--environment", help="explicit saved overlay name for the selected device")
        if name == "deploy":
            child.add_argument("--release", type=Path, help="deploy a verified compiled release bundle without building")
            child.add_argument(
                "--force",
                action="store_true",
                help="deploy even when the same graph is already running",
            )
        if name in ("deploy", "rollback"):
            child.add_argument(
                "--dry-run",
                action="store_true",
                help="build and validate, without changing the device",
            )
        if name == "rollback":
            child.add_argument("--to", help="full release ID or unique recorded prefix")
        if name == "logs":
            child.add_argument(
                "--follow",
                action="store_true",
                help="poll log tails (ring-buffer loss remains possible)",
            )
    wifi_commands = commands.add_parser(
        "wifi", help="set up or diagnose Wi-Fi over USB"
    ).add_subparsers(dest="wifi_action", required=True)
    for action in ("setup", "status", "scan", "add", "list", "forget"):
        wifi_command = wifi_commands.add_parser(action, parents=[common])
        wifi_command.add_argument(
            "--port", help="USB serial port (detected when only one board is connected)"
        )
        if action == "forget":
            wifi_command.add_argument("--ssid", required=True, help="saved network to remove")
        if action == "add":
            wifi_command.add_argument("--fallback", action="store_true", help="replace the single recovery network")
        if action in ("setup", "add"):
            wifi_command.add_argument(
                "--ssid", required=action == "add", help="network name; otherwise scan and select interactively"
            )
            password = wifi_command.add_mutually_exclusive_group()
            password.add_argument(
                "--password-file",
                type=Path,
                help="read password from a private file instead of prompting",
            )
            password.add_argument(
                "--open-network",
                action="store_true",
                help="explicitly choose an unprotected network",
            )
    devices = commands.add_parser(
        "device", help="save and select devices"
    ).add_subparsers(dest="action", required=True)
    devices.add_parser("list")
    use = devices.add_parser("use")
    use.add_argument("name")
    transport = devices.add_parser("transport")
    transport.add_argument("name")
    transport.add_argument("transport", choices=["native", "docker"])
    address = devices.add_parser("address")
    address.add_argument("name")
    address.add_argument("host")
    add = devices.add_parser("add")
    add.add_argument("name")
    add.add_argument("--host", required=True)
    add.add_argument("--certificate", type=Path, required=True)
    add.add_argument("--token-file", type=Path, required=True)
    add.add_argument(
        "--firmware",
        type=Path,
        required=True,
        help="ELF for the base currently flashed on this device",
    )
    add.add_argument(
        "--sdkconfig", type=Path, help="configuration belonging to that base ELF"
    )
    add.add_argument("--transport", choices=["native", "docker"], default="native")
    add.add_argument("--board", type=Path, help="save a verified board definition with this device")
    remove = devices.add_parser("remove", help="remove a profile while archiving its private files")
    remove.add_argument("name")
    rename = devices.add_parser("rename")
    rename.add_argument("name")
    rename.add_argument("new_name")
    refresh = devices.add_parser("refresh", help="rediscover the address over USB, verifying MAC and HTTPS identity")
    refresh.add_argument("name")
    refresh.add_argument("--port")
    environment = devices.add_parser("environment", help="save a named tunable overlay; never selects it implicitly")
    environment.add_argument("name")
    environment.add_argument("environment")
    environment.add_argument("--overlay", type=Path, required=True)
    environment.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    environment.add_argument("--board", type=Path)
    application = devices.add_parser("application", help="select the default application project for a saved device")
    application.add_argument("name")
    application.add_argument("--project", type=Path, required=True)
    bindings = devices.add_parser("board", help="select editable board bindings for future remote deployments")
    bindings.add_argument("name")
    bindings.add_argument("--board", type=Path, required=True)
    for device_command in devices.choices.values():
        device_command.add_argument("--json", action="store_true")
    init = commands.add_parser("init", help="plan, prepare, flash and pair a board over USB")
    init.add_argument("name")
    init.add_argument("--platform", choices=hardware_names())
    init.add_argument("--compiler-dir", type=Path)
    init.add_argument("--firmware", type=Path, help="platform base ELF for flash or connect")
    init.add_argument("--phase", choices=["plan", "prepare", "flash", "connect"], default="plan")
    init.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    init.add_argument("--board", type=Path, help="hardware definition to prepare and pair")
    init.add_argument("--relay-credentials", type=Path, help="private files from micros server enroll")
    init.add_argument("--credentials", type=Path, help="reuse an existing private identity when preparing")
    init.add_argument("--rotate-identity", action="store_true", help="prepare a new private identity; previous credentials remain archived")
    init.add_argument("--port")
    init.add_argument("--transport", choices=["native", "docker"], default="native")
    init.add_argument("--ssid")
    password = init.add_mutually_exclusive_group()
    password.add_argument("--password-file", type=Path)
    password.add_argument("--open-network", action="store_true")
    init.add_argument("--json", action="store_true")
    backup = commands.add_parser("backup", help="export/import private profiles, history and recovery artifacts")
    backup.add_argument("action", choices=["export", "import"])
    backup.add_argument("directory", type=Path)
    backup.add_argument("--json", action="store_true")
    release = commands.add_parser("release", parents=[common], help="export a compiled, base-specific application bundle")
    release.add_argument("directory", type=Path)
    release.add_argument("--id", help="recorded release ID; defaults to latest confirmed")
    cleanup = commands.add_parser("gc", help="prune older package bytes while retaining version/audit metadata")
    cleanup.add_argument("--keep", type=int, default=20)
    cleanup.add_argument("--dry-run", action="store_true")
    cleanup.add_argument("--json", action="store_true")
    return command


def describe(receipt):
    return (
        ", ".join(
            f"{service['name']} {service['version']}" for service in receipt["services"]
        )
        if receipt
        else "Application not recorded on this computer"
    )


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "host":
        from micros_tooling.host.cli import main as host_main
        return host_main(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "shell":
        from micros_tooling.terminal.shell import main as shell_main
        raise SystemExit(shell_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "devices":
        from micros_tooling.fleet.server import server_main
        return server_main(["devices", *sys.argv[2:]])
    if len(sys.argv) > 1 and sys.argv[1] == "server":
        from micros_tooling.fleet.server import server_main
        return server_main(sys.argv[2:])
    args = parser().parse_args()
    if args.command == "discover":
        from micros_tooling.communication.discovery import run
        run(args)
        return
    if args.command == "erase":
        from micros_tooling.deployment.erasure import erase
        result = erase(args)
        from micros_tooling.terminal.progress import color
        print(json.dumps(result, indent=2) if args.json else color(result["message"], "32", sys.stdout))
        return
    if args.command == "enroll":
        from micros_tooling.deployment.enrollment import enroll
        result = enroll(args)
        from micros_tooling.terminal.progress import color
        print(json.dumps(result, indent=2) if args.json else color(result["message"], "32", sys.stdout))
        return
    if args.command == "generate" and args.service:
        require(not any(getattr(args, k, None) for k in ('device', 'project', 'board', 'platform')),
                '--service selects a reusable contract; remove board/project/platform selectors')
        from micros_tooling.config.generation_cli import run
        run(Path.cwd(), args.service, args.output, args.json)
        return
    if args.command == 'contract-diff':
        from micros_tooling.config.contract_diff import compare, display
        display(compare(args.declaration, args.base), args.json, args.stubs)
        return
    if args.command == "scaffold-service":
        args.new = args.new or bool(args.example)
        require(not args.new or not (args.preview or args.base), '--new cannot be combined with --preview or --base.')
        if args.base:
            require(args.preview, '--base requires --preview; implementation files are never rewritten')
            from micros_tooling.config.contract_diff import compare, display
            display(compare(args.contract, args.base), args.json, True)
            return
        from micros_tooling.config.service_scaffold import create, artifacts, new
        if args.preview:
            _, files = artifacts(args.contract)
            print(json.dumps({str(k):v for k,v in files.items()}, indent=2) if args.json else files[Path("src/service.c")])
            return
        created = new(args.contract, args.example) if args.new else create(args.contract)
        if args.json:
            print(json.dumps(dict(files=list(map(str, created))), indent=2))
            return
        for path in created:
            print("Created: " + str(path))
        import shlex
        print('Generate interfaces with: ' + shlex.join(['./micros', 'generate', '--service', str(args.contract)]))
        if args.example:
            print('Counter commands: read, increment, reset. State resets when the service restarts.')
        else:
            print("Implement TODOs before deployment; GPIO/channel bindings still belong to the selected unit.")
        if args.new:
            print('Select this service in host.toml or units/<hardware-id>.toml before building it.')
        return
    if args.command == "scaffold-commands":
        from micros_tooling.commands.generate import scaffold
        print("Created handlers: " + str(scaffold(args.contract, args.output)))
        print("Add this file to service.build.sources; integrate generated commands_open/step/close into the service lifecycle.")
        return
    if args.command == "new":
        from micros_tooling.config.scaffold import create
        destination = create(args.directory, platform=args.platform)
        print(f"Created application: {destination}\nSee {destination / 'README.md'} for host tests and board enrollment.")
        return
    if os.environ.get("MICROS_APPLICATION_ROOT") and hasattr(args, "project"):
        require(args.project is not None or getattr(args, "release", None),
                "Application projects require --project PATH to a composed unit recipe; "
                "run micros compose first. SDK example defaults are not selected here.")
    if args.command == "pins":
        from micros_tooling.config.chips import pin_listing, format_pins
        report = pin_listing(dict(profile=args.profile))
        print(json.dumps(report, indent=2) if args.json else
              format_pins(report, all_pins=args.all, pin_number=args.pin))
        return
    if args.command == "compose":
        from micros_tooling.config.composition import compose, describe as describe_composition, write
        result = compose(args.deployment)
        output = write(result, args.output) if args.output else None
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(describe_composition(result))
            print(f"\nValidated recipes: {output}" if output else "\nValid configuration. Use --output DIRECTORY to write reviewed recipes.")
        return
    from micros_tooling.deployment.selection import resolve_enrolled_platform
    resolve_enrolled_platform(args)
    from micros_tooling.platforms import handler_for
    platform_handler = handler_for(args)
    if platform_handler is not None:
        require(args.command != "restart", "Individual service restart currently requires an ESP32 base.")
        require(not getattr(args, "planning", False),
                "Structured plans currently support ESP32 deployment; use deploy --dry-run for this platform.")
        from micros_tooling.terminal.progress import Activity
        labels = dict(status='Reading controller status', doctor='Checking controller',
                      deploy='Deploying application', build='Building application',
                      stop='Stopping application', recover='Recovering application',
                      reboot='Restarting controller', rollback='Restoring previous application',
                      wifi='Updating Wi-Fi', **{'base-update': 'Updating base firmware'})
        if args.command in labels:
            with Activity(labels[args.command]):
                return platform_handler(args)
        return platform_handler(args)

    needs_project = args.command in ("config", "generate", "build", "deploy") or (
        args.command == "init" and args.phase == "prepare") or (
        args.command == "device" and args.action == "environment")
    if needs_project and not getattr(args, "release", None):
        require(getattr(args, "project", None) is not None,
                "SDK commands require --project PATH to an application recipe. "
                "Run the application's ./micros launcher to select its unit automatically.")

    def progress(phase, message):
        print(f"  {message}", file=sys.stderr, flush=True)

    if args.command == "base-update":
        from micros_tooling.deployment.base_ota import update_base
        from micros_tooling.fleet.server import discover_for_command
        from micros_tooling.deployment.diagnostics import connect
        state = Workspace(Path(os.environ.get("MICROS_STATE_DIR", ROOT / ".micros")))
        found = discover_for_command(state, args)
        connection = found[0] if found else connect(state, args.device)[2]
        result = update_base(connection, args.firmware, args.image,
                             dry_run=args.dry_run, progress=progress)
        print(json.dumps(result) if args.json else
              "Base image fits and is compatible; no changes made." if args.dry_run else
              "Base OTA confirmed. Build and deploy applications against the new base ELF.")
        return

    if args.command in ("build", "deploy", "rollback", "history", "status", "logs", "stop", "recover", "restart", "reboot", "doctor") and not (args.command == "build" and args.firmware):
        from micros_tooling.fleet.server import discover_for_command
        state = Workspace(Path(os.environ.get("MICROS_STATE_DIR", ROOT / ".micros")))
        discovered = discover_for_command(state, args)
        if discovered:
            connection, selected, paired = discovered
            progress("server", f"Server device: {selected['name']} ({selected['device_id']})")
            if not paired:
                status = connection.status()
                if args.command in ("status", "doctor"):
                    print(json.dumps(status, indent=2))
                elif args.command == "restart":
                    from micros_tooling.deployment.service_control import restart_service
                    result = restart_service(connection, args.service_index)
                    print(json.dumps(result) if args.json else f"Service {args.service_index} restarted; peers preserved.")
                elif args.command == "logs":
                    from micros_tooling.communication.logs import follow_logs
                    for event in follow_logs(connection, follow=args.follow):
                        if args.json:
                            print(json.dumps(dict(device=selected['name'], **event)), flush=True)
                        elif event['event'] == 'logs':
                            print(event['logs'], end='', flush=True)
                        else:
                            print(json.dumps(event), file=sys.stderr, flush=True)
                else:
                    with connection.deployment_session(status):
                        if args.command == "recover":
                            selection = status["activation"]
                            require(not selection["pending"] and selection["good"] in (0,1), "No recoverable selected application")
                            result = connection.request("POST", f'/v1/activate?bank={selection["good"]}', bytes.fromhex(selection["good_sha256"]))
                        else:
                            result = connection.request("POST", "/v1/pause" if args.command == "stop" else "/v1/reboot")
                    print(json.dumps(result))
                return

    if args.command in ("generate", "config", "build", "deploy") and not getattr(args, "release", None):
        from micros_tooling.config.resources import select_board
        from micros_tooling.config.configuration import select_unit, read_toml
        progress("project", "Application: " + str(args.project))
        selected = args.board
        embedded = args.project.suffix == ".toml" and "board" in read_toml(args.project)
        if selected is None and not embedded and not getattr(args, "firmware", None):
            state = Workspace(Path(os.environ.get("MICROS_STATE_DIR", ROOT / ".micros")))
            profiles = state.profiles()
            device = args.device or profiles["default"]
            if device in profiles["devices"] and profiles["devices"][device].get("board"):
                selected = Path(profiles["devices"][device].get("board_source", state.root / "devices" / device / "board.toml"))
        args.board = select_board(args.project, selected)
        if args.board:
            progress("board", f"Board definition: {args.board}")

    if args.command == "generate":
        from micros_tooling.config.configuration import generate_service_headers

        headers = generate_service_headers(args.project, args.board)
        print(
            json.dumps({"headers": [str(path) for path in headers]})
            if args.json
            else "Generated service headers:\n"
            + "\n".join(str(path) for path in headers)
        )
        return
    if args.command == "config":
        from micros_tooling.config.configuration import load_project, config_artifacts

        recipe = load_project(args.project, args.overlay, args.board)
        resolved = {}
        for service in recipe["services"]:
            if "_configuration" in service:
                specification = service["_configuration"]
                config_artifacts(
                    specification["name"],
                    specification["definition"],
                    specification["values"],
                )
                resolved[specification["name"]] = {
                    field: specification["values"].get(field, spec["default"])
                    for field, spec in specification["definition"]["fields"].items()
                }
        print(json.dumps(resolved, indent=2))
        return
    if args.command == "build" and args.firmware:
        require(not args.environment, "Review builds use --overlay PATH; named environments belong to saved devices.")
        require(
            args.output is not None,
            "--firmware review builds require --output DIRECTORY",
        )
        packages = build_application(
            args.project, args.firmware, args.output, progress, args.overlay, args.board
        )
        from micros_tooling.platforms.esp32.device import prepare

        prepare(packages, args.firmware, 0)
        if args.bundle:
            from micros_tooling.storage.bundles import export_packages
            export_packages(packages, args.firmware, args.bundle)
        print(
            json.dumps({"packages": [str(path) for path in packages]})
            if args.json
            else f"Built {len(packages)} services for review in {args.output}"
        )
        return
    if args.command == "build":
        require(args.output is None, "--output requires --firmware")
    workspace = Workspace(Path(os.environ.get("MICROS_STATE_DIR", ROOT / ".micros")))
    if args.command == "gc":
        from micros_tooling.storage.retention import collect
        with workspace.locked():
            result = collect(workspace, args.keep, args.dry_run)
        print(json.dumps(result, indent=2))
        return
    if args.command in ("backup", "release"):
        from micros_tooling.storage.bundles import export_state, import_state, export_release
        with workspace.locked():
            if args.command == "backup":
                result = (export_state if args.action == "export" else import_state)(workspace, args.directory)
                if args.action == "export":
                    progress("privacy", "Private backup includes credentials, firmware and Wi-Fi-containing flash backups. Store it privately.")
            else:
                name, _ = workspace.device(args.device)
                result = export_release(workspace, name, args.id, args.directory)
        print(json.dumps(result, indent=2))
        return
    if args.command == "init":
        from micros_tooling.deployment.onboarding import onboard
        with workspace.locked():
            result = onboard(workspace, args, progress)
        print(json.dumps(result, indent=2))
        return

    # Observation must remain available while another terminal builds/deploys,
    # and must not require an ELF that is irrelevant to network diagnostics.
    if args.command in ("doctor", "status", "history", "recover", "restart", "stop", "reboot"):
        from micros_tooling.deployment.diagnostics import connect, doctor, show_status
        if args.command == "doctor":
            result = doctor(workspace, args.device)
            if args.json:
                print(json.dumps(result))
            else:
                for check in result["checks"]:
                    print(f"{'OK' if check['okay'] else 'FAIL'} {check['check']}: {check['detail']}")
            if not result["okay"]:
                sys.exit(1)
            return
        name, profile = workspace.device(args.device)
        if args.command == "history":
            from micros_tooling.fleet.server import RelayRemote
            from micros_tooling.fleet.server import configured_remote, connect_profile
            history_remote = configured_remote(workspace, profile.get('device_id') or profile.get('mac', '').replace(':', ''))
            if history_remote is None and profile.get('relay'):
                history_remote = connect_profile(workspace, name, profile)
            if isinstance(history_remote, RelayRemote):
                from micros_tooling.storage.artifacts import sync_releases
                with workspace.locked(device=name):
                    sync_releases(history_remote, workspace, name)
            history = workspace.history(name)
            if args.json:
                print(json.dumps(history))
            else:
                for event in history:
                    receipt = workspace.read(Path("snapshots") / event["snapshot"] / "receipt.json")
                    print(f'{event["confirmed_at"]}  {event["snapshot"]}  {describe(receipt)}')
                if not history:
                    print("No confirmed deployments saved yet.")
            return
        _, _, remote = connect(workspace, name)
        status = remote.status()
        receipt = workspace.matching(status, name)
        if args.command == "status":
            from micros_tooling.deployment.attempts import observe_attempt
            attempt = observe_attempt(workspace, name, status)
            # Reconcile after an interrupted client when no writer holds the lock.
            try:
                with workspace.locked(device=name):
                    receipt = workspace.observe(name, status)
            except (ValueError, OSError, KeyError, TypeError):
                pass
            if args.json:
                print(json.dumps(dict(device=name, application=receipt, status=status, attempt=attempt)))
            else:
                show_status(name, status, receipt)
                if attempt:
                    print(f"Last deployment phase: {attempt['phase']} · {attempt['observed']}")
            return
        with workspace.locked(device=name):
            status = remote.status()
            if args.command == "restart":
                from micros_tooling.deployment.service_control import restart_service
                result = restart_service(remote, args.service_index)
                print(json.dumps(result) if args.json else f"Service {args.service_index} restarted; peers preserved.")
                return
            if args.command in ("stop", "reboot"):
                with remote.deployment_session(status):
                    result = remote.request("POST", "/v1/pause" if args.command == "stop" else "/v1/reboot")
                print(json.dumps(result) if args.json else
                      "Application paused; use micros recover to restart." if args.command == "stop" else "Device reboot requested.")
                return
            selection = status["activation"]
            require(not selection["pending"], "A trial is pending. Observe status before recovery.")
            require(selection["good"] != NO_BANK, "No selected application. Deploy an application first.")
            if not status["services"] or not running(status, len(status["services"])):
                with remote.deployment_session(status):
                    remote.request("POST", f'/v1/activate?bank={selection["good"]}',
                                   bytes.fromhex(selection["good_sha256"]))
                status = remote.status()
            require(status["activation"]["good_sha256"] == selection["good_sha256"]
                    and not status["activation"]["pending"] and status["services"]
                    and running(status, len(status["services"])), "Recovery not confirmed. Inspect status and logs.")
            print(json.dumps(status) if args.json else "Selected application is running.")
        return

    if args.command == "wifi":
        from micros_tooling.communication.wifi import (
            Wifi,
            select_port,
            display_ssid,
            setup_from_terminal,
        )

        with workspace.locked():
            profiles = workspace.profiles()
            name = args.device or profiles["default"]
            if args.device:
                require(name in profiles["devices"], "Unknown device: " + name)
            profile = profiles["devices"].get(name)
            port = select_port(args.port, (profile or {}).get("serial_port"))
            progress("usb", "Connecting over USB: " + port)
            wifi = Wifi(port)
            try:
                initial = wifi.status()
                if profile and profile.get("mac"):
                    require(
                        profile["mac"] == initial["mac"],
                        "This USB board does not match the saved device. Select the correct --device or --port.",
                    )
                if args.wifi_action == "setup":
                    result = setup_from_terminal(
                        wifi, args, lambda message: progress("wifi", message)
                    )
                    if profile:
                        profile.update(
                            host=result["ip"], mac=result["mac"], serial_port=port
                        )
                        workspace.write("devices.json", profiles)
                    if args.json:
                        print(json.dumps(result))
                    else:
                        print(
                            f"Connected to {display_ssid(result['ssid_hex'])}: {result['ip']}"
                        )
                        print(
                            "Wi-Fi settings saved on the device."
                            + (
                                f" Updated {name}; ./micros deploy is ready."
                                if profile
                                else ""
                            )
                        )
                elif args.wifi_action in ("add", "list", "forget"):
                    if args.wifi_action == "add":
                        result = setup_from_terminal(wifi, args, lambda message: progress("wifi", message))
                    elif args.wifi_action == "forget":
                        result = wifi.forget(args.ssid.encode("utf-8"))
                    else:
                        result = {"saved_networks": wifi.saved_networks()}
                    if args.json:
                        print(json.dumps(result))
                    else:
                        for index, network in enumerate(result["saved_networks"], 1):
                            role = "fallback" if network["fallback"] else f"primary {index}"
                            print(f"{role}: {display_ssid(network['ssid_hex'])}")
                        if not result["saved_networks"]:
                            print("No saved Wi-Fi networks.")
                elif args.wifi_action == "scan":
                    networks = wifi.scan()
                    if args.json:
                        print(json.dumps(networks))
                    else:
                        for network in networks:
                            print(
                                f"{display_ssid(network['ssid_hex'])} · {network['rssi']} dBm"
                                + (" · open" if network["open"] else "")
                            )
                else:
                    initial = wifi.settled_status()
                    if args.json:
                        print(json.dumps(initial))
                    else:
                        print("Wi-Fi: " + initial["state"].replace("_", " "))
                        if initial["ssid_hex"]:
                            print("Network: " + display_ssid(initial["ssid_hex"]))
                        if initial["state"] == "connected":
                            print("IP address: " + initial["ip"])
                        else:
                            print("Connection: " + initial["reason"].replace("_", " "))
                        print(
                            "Saved on device: " + ("yes" if initial["saved"] else "no")
                        )
            finally:
                wifi.close()
        return
    if args.command == "logs":
        name, profile = workspace.device(args.device)
        certificate, token, _ = workspace.files(name)
        from micros_tooling.deployment.diagnostics import connect
        remote = connect(workspace, name)[2]
        from micros_tooling.communication.logs import follow_logs
        if "identity" not in remote.status():
            require(not args.follow, "This base supports only a log tail. Migrate over USB for loss-aware --follow.")
            tail = remote.request("GET", "/v1/logs")
            print(json.dumps(dict(device=name, logs=tail)) if args.json else tail)
            return
        for event in follow_logs(remote, args.follow):
            if args.json:
                print(json.dumps(dict(device=name, **event)), flush=True)
            elif event["event"] == "logs":
                print(event["logs"], end="", flush=True)
            else:
                print("\n" + json.dumps(event), file=sys.stderr, flush=True)
        return
    lock_device = None if args.command == "device" else (args.device or workspace.profiles()["default"])
    with workspace.locked(device=lock_device):
        if args.command == "device":
            profiles = workspace.profiles()
            if args.action == "add":
                configuration = args.sdkconfig or (args.firmware.parent / "sdkconfig")
                workspace.add_device(
                    args.name,
                    args.host,
                    args.certificate,
                    args.token_file,
                    args.firmware,
                    configuration if configuration.is_file() else None,
                    args.transport,
                    args.board,
                )
                print(json.dumps(dict(device=args.name, saved=True, verified=False)) if args.json else
                      f"Saved {args.name}. Run ./micros doctor -d {args.name} to verify readiness.")
            elif args.action == "list":
                if args.json:
                    print(json.dumps(profiles))
                    return
                for name, profile in profiles["devices"].items():
                    print(
                        f'{"*" if name == profiles["default"] else " "} {name:16} {profile["host"]} ({profile["transport"]})'
                    )
                if not profiles["devices"]:
                    print("No saved devices. Run ./micros device add --help.")
            else:
                require(
                    args.name in profiles["devices"], f"Unknown device: {args.name}"
                )
                if args.action == "use":
                    profiles["default"] = args.name
                elif args.action == "transport":
                    profiles["devices"][args.name]["transport"] = args.transport
                elif args.action == "rename":
                    from micros_tooling.storage.packages import identifier
                    identifier(args.new_name, "device name")
                    require(args.new_name not in profiles["devices"], "New name already exists")
                    (workspace.root / "devices" / args.name).rename(workspace.root / "devices" / args.new_name)
                    profiles["devices"][args.new_name] = profiles["devices"].pop(args.name)
                    if profiles["default"] == args.name:
                        profiles["default"] = args.new_name
                elif args.action == "remove":
                    import uuid
                    archive = workspace.root / "retired" / (args.name + "-" + uuid.uuid4().hex)
                    archive.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    (workspace.root / "devices" / args.name).rename(archive)
                    del profiles["devices"][args.name]
                    if profiles["default"] == args.name:
                        profiles["default"] = next(iter(profiles["devices"]), None)
                elif args.action == "refresh":
                    from micros_tooling.communication.wifi import Wifi, select_port
                    profile = profiles["devices"][args.name]
                    wifi = Wifi(select_port(args.port, profile.get("serial_port")))
                    try:
                        observed = wifi.settled_status()
                    finally:
                        wifi.close()
                    require(profile.get("mac") and profile["mac"] == observed["mac"],
                            "USB MAC is unknown or does not match the saved board. Use init connect to pair explicitly.")
                    require(observed["state"] == "connected", "Board has no IP. Run micros wifi setup.")
                    certificate, token, _ = workspace.files(args.name)
                    connection = (DockerRemote if profile["transport"] == "docker" else Remote)(observed["ip"], certificate, token)
                    connection.status()  # Verify the saved TLS identity before changing its address.
                    profile["host"] = observed["ip"]
                elif args.action == "board":
                    from micros_tooling.config.resources import load_board, verify_board_firmware
                    definition=load_board(args.board)
                    verify_board_firmware(definition,workspace.files(args.name)[2])
                    profiles["devices"][args.name]["board_source"]=str(args.board.resolve())
                elif args.action == "application":
                    from micros_tooling.config.configuration import load_project
                    profile = profiles["devices"][args.name]
                    board = Path(profile.get("board_source", workspace.root / "devices" / args.name / "board.toml")) if profile.get("board") else None
                    recipe = load_project(args.project, board=board)
                    require(recipe["services"], "Select an application with at least one enabled service")
                    profile["application"] = str(args.project.resolve())
                elif args.action == "environment":
                    from micros_tooling.storage.packages import identifier
                    from micros_tooling.config.configuration import load_project, config_artifacts
                    from micros_tooling.storage.store import atomic_write
                    identifier(args.environment, "environment name")
                    board = args.board or (workspace.root / "devices" / args.name / "board.toml"
                                           if profiles["devices"][args.name].get("board") else None)
                    recipe = load_project(args.project, args.overlay, board)
                    for service in recipe["services"]:
                        config = service.get("_configuration")
                        if config:
                            config_artifacts(config["name"], config["definition"], config["values"])
                    filename = "environments/" + args.environment + ".toml"
                    atomic_write(workspace.root / "devices" / args.name / filename, args.overlay.read_bytes())
                    profiles["devices"][args.name].setdefault("environments", {})[args.environment] = filename
                else:
                    profiles["devices"][args.name]["host"] = args.host
                workspace.write("devices.json", profiles)
                print(json.dumps(dict(device=args.name, updated=True)) if args.json else f"Updated {args.name}.")
            return
        name, profile = workspace.device(args.device)
        certificate, token, firmware = workspace.files(name)
        from micros_tooling.fleet.server import RelayRemote
        from micros_tooling.deployment.diagnostics import connect
        artifact_remote = connect(workspace, name)[2] if args.command in ("build", "deploy", "rollback") else None
        if isinstance(artifact_remote, RelayRemote):
            from micros_tooling.storage.artifacts import fetch_base, sync_releases
            live = artifact_remote.status()
            expected = profile.get("device_id") or profile.get("mac", "").replace(":", "")
            require(live.get("identity", {}).get("device_id") == expected,
                    "Authenticated board does not match selected hardware")
            firmware = fetch_base(artifact_remote, workspace, live)
            progress("base", "Verified server base: " + live["identity"]["base_sha256"])
            sync_releases(artifact_remote, workspace, name)
        else:
            require(digest(firmware.read_bytes()) == profile["firmware_sha256"],
                    "Paired base ELF changed; restore the original paired file.")
        if getattr(args, "environment", None):
            require(not args.overlay and not getattr(args, "release", None),
                    "Choose a saved environment, an overlay, or a compiled release; do not combine them.")
            filename = profile.get("environments", {}).get(args.environment)
            require(filename, "Unknown saved environment. Use micros device environment NAME ENV --overlay PATH.")
            args.overlay = workspace.root / "devices" / name / filename
            progress("environment", "Environment: " + args.environment + " (explicit saved overlay)")
        if args.command == "build":
            packages = build_application(
                args.project,
                firmware,
                workspace.root / "build" / name,
                progress,
                args.overlay,
                args.board,
            )
            # Admission checks are local, including slot linkage against the paired base.
            from micros_tooling.platforms.esp32.device import prepare

            _, _, plan = prepare(packages, firmware, 0)
            if args.bundle:
                from micros_tooling.storage.bundles import export_packages
                export_packages(packages, firmware, args.bundle)
            print(
                json.dumps(dict(packages=[str(path) for path in packages], plan=plan))
                if args.json
                else f"Built {len(packages)} services. Packages: {workspace.root / 'build' / name}"
            )
            return
        from micros_tooling.deployment.diagnostics import connect
        remote = connect(workspace, name)[2]
        progress("connect", f'{name} via {remote.host}:{remote.port}')
        status = remote.status()
        expected_device = profile.get("device_id") or profile.get("mac", "").replace(":", "")
        if expected_device and status.get("identity"):
            require(status["identity"].get("device_id") == expected_device,
                    "Authenticated board does not match the saved hardware identity. Check the selected profile.")
        from micros_tooling.deployment.identity import verify_base
        verify_base(status, firmware)
        receipt = workspace.observe(name, status)
        if args.command == "deploy":
            if args.release:
                from micros_tooling.storage.bundles import release_packages
                require(not args.overlay, "A compiled release already includes settings; --overlay is not allowed.")
                packages = release_packages(args.release, firmware)
            else:
                from micros_tooling.config.configuration import select_unit
                select_unit(args.project.parent, status.get("identity", {}).get("device_id"), args.project)
                packages = build_application(
                    args.project,
                    firmware,
                    workspace.root / "build" / name,
                    progress,
                    args.overlay,
                    args.board,
                )
        else:
            receipt = workspace.rollback_target(name, status, args.to)
            packages = workspace.snapshot_packages(receipt, firmware)
            progress("rollback", "Restoring saved packages: " + describe(receipt))
        inspection = inspect_deployment(remote, packages, firmware)
        # Content hashes identify releases; service versions are descriptive labels.
        receipt = workspace.snapshot(packages, inspection, firmware)
        packages = workspace.snapshot_packages(receipt, firmware)
        current_receipt = workspace.matching(inspection["before"], name)
        from micros_tooling.deployment.preview import changes
        from micros_tooling.deployment.planning import deployment_plan, format_plan
        difference = changes(current_receipt, receipt)
        report = deployment_plan(inspection, current_receipt, receipt, device=name,
                                 force=getattr(args, "force", False))
        for service, detail in receipt.get("details", {}).items():
            if "headroom" in detail:
                free = detail["headroom"]
                progress("memory", f"{service}: slot {detail['slot']}, {free['code_bytes']} code bytes and {free['data_bytes']} data bytes free")
        if args.dry_run:
            print(
                json.dumps(
                    dict(dry_run=True, application=receipt, changes=difference,
                         plan=inspection["plan"], deployment_plan=report)
                )
                if args.json
                else format_plan(report) + "\n\nDry run passed. No device changes made."
            )
            return
        progress("plan", format_plan(report))
        if isinstance(remote, RelayRemote):
            from micros_tooling.storage.artifacts import archive_release
            configuration = {}
            if args.command == "deploy" and not args.release:
                configuration["unit_toml"] = args.project.read_text()
                if args.overlay:
                    configuration["overlay_toml"] = args.overlay.read_text()
                resolved = workspace.root / "build" / name / "resolved.json"
                if resolved.exists():
                    configuration["resolved"] = json.loads(resolved.read_text())
            else:
                saved = workspace.root / "snapshots" / receipt["id"] / "configuration.json"
                if saved.exists():
                    configuration = json.loads(saved.read_text())
            archive_release(remote, receipt, packages, configuration)
        from micros_tooling.deployment.attempts import recorded_deploy
        result = recorded_deploy(
            workspace, name, receipt,
            remote,
            packages,
            firmware,
            progress=progress,
            force=getattr(args, "force", False),
            prepared=inspection,
        )
        workspace.confirm(name, receipt)
        if isinstance(remote, RelayRemote):
            from micros_tooling.storage.artifacts import confirm_release
            try:
                confirm_release(remote, receipt, result["status"])
            except (OSError, ValueError, http.client.HTTPException) as error:
                progress("archive", "Deployment succeeded; server confirmation is pending: " + str(error))
        if hasattr(remote, "register_release"):
            try:
                remote.register_release(inspection)
            except (OSError, ValueError, http.client.HTTPException) as error:
                progress("labels", "Deployment succeeded; console labels could not be updated: " + str(error))
        print(
            json.dumps(dict(device=name, snapshot=receipt["id"], **result))
            if args.json
            else f'{name}: {"already up to date" if result["unchanged"] else "deployment complete"}. All {len(receipt["services"])} services are running.'
        )


def entrypoint(args):
    """Execute an already resolved command with one error/interrupt policy."""
    sys.argv = ["micros", *args]
    try:
        return main() or 0
    except SystemExit as error:
        return error.code
    except KeyboardInterrupt as error:
        if len(sys.argv) > 1 and sys.argv[1] == "logs":
            sys.exit(0)  # Ctrl-C finishes a read-only log stream; no deployment is uncertain.
        from micros_tooling.deployment.enrollment import EnrollmentCancelled
        message = (str(error) if isinstance(error, EnrollmentCancelled) else
                   "Enrollment canceled." if len(sys.argv) > 1 and sys.argv[1] == "enroll" else "Cancelled.")
        print(json.dumps(dict(error=dict(code="cancelled", message=message, outcome="unknown")))
              if "--json" in sys.argv else "\n" + message, file=sys.stderr)
        sys.exit(130)
    except (
        EOFError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        http.client.HTTPException,
    ) as error:
        message = str(error)
        offline = len(sys.argv) > 1 and sys.argv[1] in ('generate', 'compose', 'config', 'scaffold-service', 'scaffold-commands', 'contract-diff')
        if isinstance(error, EOFError):
            message = 'Terminal input closed. Rerun the command in an interactive terminal to continue.'
        elif isinstance(error, ssl.SSLCertVerificationError):
            message = "Device certificate did not verify. Check the saved device certificate and address."
        elif isinstance(error, FileNotFoundError):
            message = "Required local file or executable is missing: " + str(error.filename)
        elif isinstance(error, PermissionError):
            message = "Local file or network permission denied: " + str(error)
        elif isinstance(error, OSError) and not offline:
            message += "\nRun ./micros doctor to distinguish transport, identity and local setup failures."
        if "--json" in sys.argv:
            print(json.dumps(dict(error=dict(code=getattr(error, "code", type(error).__name__), message=message,
                outcome=getattr(error, "outcome", "not_confirmed"),
                retryable=getattr(error, "retryable", False),
                details=getattr(error, "details", None),
                next_action="Rerun the command in an interactive terminal." if isinstance(error, EOFError) else
                    "Correct the referenced declaration and rerun this command." if offline else "Run micros doctor, status or logs for the affected device."))), file=sys.stderr)
        else:
            print("micros: " + message, file=sys.stderr)
        sys.exit(1)
