"""Select one physical board's complete unit recipe and invoke the SDK."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from micros_tooling.config.configuration import load_project, unit_identity
from micros_tooling.dispatch import CommandParser

def select_unit(requested=None, *, root, state=None):
    paths = sorted((root / "units").glob("*.toml"))
    units = {unit_identity(path): path for path in paths}
    if None in units or len(units) != len(paths):
        raise ValueError("Each unit must declare its unique hardware identity")
    if requested:
        identity = requested
        if identity not in units:
            state = state or Path(os.environ["MICROS_STATE_DIR"])
            from micros_tooling.storage.workspace import Workspace
            from micros_tooling.fleet.server import configured_remote, choose_device
            remote = configured_remote(Workspace(state))
            if remote is None:
                raise ValueError("Server connection required to resolve a device name; use a hardware ID offline")
            devices = json.loads(remote.raw('GET', '/v1/devices'))['devices']
            identity = choose_device(devices, requested, require_online=False)['device_id']
        if identity not in units:
            raise ValueError(f"No unit for {requested!r}; use a hardware ID or matching server device")
        return units[identity]
    if len(units) != 1:
        raise ValueError("Select -d DEVICE; available units: " + ", ".join(units))
    return next(iter(units.values()))


def main(args, root, dispatch):
    """Apply project defaults; SDK selection belongs to the CLI boundary."""
    root = Path(root).resolve()
    from micros_tooling.storage.client import application_cache
    os.environ.setdefault("MICROS_STATE_DIR", str(application_cache(root)))
    if not args or args == ["--help"]:
        print("""micros application — one complete units/<hardware-id>.toml per board

  ./micros compose [-d HARDWARE_ID] [--json]
                                        offline validation and resolved recipe
  ./micros generate --service services/NAME
                                        generate board-independent service interfaces
  ./micros generate                     generate all local service interfaces
  ./micros scaffold-service services/NAME
                                        create application hooks and state once
  ./micros scaffold-commands CONTRACT --output FILE
                                        create command handler stubs once
  ./micros pins [-d HARDWARE_ID] [--pin N | --all | --json]
                                        service connections and unused pins
  ./micros host deploy                   build and activate host.toml locally
  ./micros host status|logs|stop|boot     manage the local native application
  ./micros test                          offline host tests
  ./micros plan -d feather [--json]       preview changes and deployment impact
  ./micros deploy -d feather --dry-run    preview one board's deployment
  ./micros deploy -d feather              deploy one board
  ./micros devices                        live management roster
  ./micros erase                          remove from console and erase firmware and settings
  ./micros discover                       identify connected micros controllers over USB
  ./micros enroll                         detect, flash, join Wi-Fi and verify console enrollment
  ./micros shell -d feather               interactive inspection and service commands
  ./micros status -d feather
  ./micros restart INDEX -d feather       restart one service by its status index
  ./micros logs -d feather
  ./micros sdk COMMAND ...                explicit SDK passthrough

The sole unit can be selected automatically; multiple units require -d.
Device names resolve through the server; hardware IDs work directly.
Communication between boards is optional and is not configured by this launcher.
""")
        return 0
    if args and args[0] == "generate" and not any(a in ("-d", "--device", "--project", "--board") or a.startswith(("--device=", "--project=", "--board=", "-d")) for a in args[1:]):
        parser = CommandParser(prog="micros generate", description="Generate local service interfaces without a board")
        parser.add_argument('--service', type=Path)
        parser.add_argument('--output', type=Path)
        parser.add_argument('--json', action='store_true')
        options = parser.parse_args(args[1:])
        from micros_tooling.config.generation_cli import run
        run(root, options.service, options.output, options.json)
        return 0
    if args == ["test"]:
        return subprocess.call([sys.executable, "-m", "unittest", "discover",
                                "-s", str(root / "tests"), "-p", "*_test.py"])
    if args[0] == "host":
        from micros_tooling.host.cli import main as host_main
        if not any(a == "--project" or a.startswith("--project=") for a in args) and len(args) > 1 and args[1] != "--help":
            args += ["--project", str(root / "host.toml")]
        host_main(args[1:])
        return 0
    command = args[0]
    if command == "sdk":
        args = args[1:]
    elif command in ("compose", "pins", "config", "generate", "build", "deploy", "plan") and not any(
        arg in ("--project", "--release") or arg.startswith(("--project=", "--release="))
        for arg in args
    ):
        parser = CommandParser(add_help=False, allow_abbrev=False)
        parser.add_argument("-d", "--device")
        if command == "pins":
            view = parser.add_mutually_exclusive_group()
            view.add_argument("--pin", type=int)
            view.add_argument("--all", action="store_true")
            view.add_argument("--json", action="store_true")
        options, rest = parser.parse_known_args(args[1:])
        if "--help" in rest and command not in ("compose", "pins"):
            return dispatch([command, "--help"])
        if command in ("compose", "pins") and any(arg != "--json" for arg in rest):
            raise ValueError(f"{command} accepts -d DEVICE and --json")
        path = select_unit(options.device, root=root)
        if command == "pins":
            from micros_tooling.config.chips import unit_pin_listing, format_pins
            report = unit_pin_listing(path)
            print(json.dumps(report, indent=2) if options.json else
                  format_pins(report, all_pins=options.all, pin_number=options.pin))
            return 0
        if command == "compose":
            recipe = load_project(path)
            if "--json" in rest:
                print(json.dumps(recipe, indent=2))
            else:
                print(f"{path.name}: " + ", ".join(s["name"] for s in recipe["services"]))
            return 0
        args = [command, "--project", str(path), *rest]
        if command in ("build", "deploy", "plan"):
            args += ["-d", unit_identity(path)]
    return dispatch(args)
