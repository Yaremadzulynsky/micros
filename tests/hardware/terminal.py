#!/usr/bin/env python3
"""Exercise the terminal OTA flow, temporarily remove C++, then restore the color graph.

Run explicitly on a provisioned Feather; this test changes its selected services.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--project", type=Path, required=True,
                        help="explicit board unit containing the four-service reference graph")
    parser.add_argument("--reduced-project", type=Path, required=True,
                        help="unit for the same board with board.cpp removed")
    parser.add_argument("--output", type=Path, default=ROOT / "build/terminal-hardware")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    def run(label, command, *options):
        if command == "deploy" and "--project" not in options:
            options = ("--project", args.project, *options)
        process = subprocess.run(
            [
                str(ROOT / "micros"),
                command,
                "-d",
                args.device,
                "--json",
                *map(str, options),
            ],
            text=True,
            stdout=subprocess.PIPE,
            timeout=180,
        )
        (args.output / (label + ".json")).write_text(process.stdout)
        if process.returncode:
            raise RuntimeError(
                f"{command} failed; inspect ./micros status before retrying."
            )
        return json.loads(process.stdout)

    from micros_tooling.config.configuration import load_project, unit_identity
    recipe = load_project(args.project)
    reduced = load_project(args.reduced_project)
    assert len(recipe["services"]) == 4
    assert any(service["name"] == "board.cpp" for service in recipe["services"])
    assert unit_identity(args.project) and unit_identity(args.project) == unit_identity(args.reduced_project)
    assert sorted(service["name"] for service in reduced["services"]) == sorted(
        service["name"] for service in recipe["services"] if service["name"] != "board.cpp")
    before = run("before", "status")["status"]
    run("dry-run", "deploy", "--dry-run")
    after = run("after-dry-run", "status")["status"]
    assert (
        before["activation"] == after["activation"]
    ), "Dry run changed the device selection"
    baseline = run("baseline", "deploy")
    # A failed activation has its own recovery. Never blindly issue another
    # mutation from a finally block when the remote outcome is unknown.
    changed = run("three-services", "deploy", "--project", args.reduced_project)
    assert len(changed["status"]["services"]) == 3 and not changed["unchanged"]
    restored = run("rollback", "rollback", "--to", baseline["snapshot"])
    assert len(restored["status"]["services"]) == 4
    assert (
        restored["status"]["activation"]["good_sha256"]
        == baseline["status"]["activation"]["good_sha256"]
    )
    unchanged = run("no-op", "deploy")
    assert unchanged["unchanged"]
    assert unchanged["status"]["activation"] == restored["status"]["activation"]
    run("logs", "logs")
    run("history", "history")
    print(
        "PASS: dry run, four → three services, rollback to four, and no-op deployment. Button/colors restored."
    )


if __name__ == "__main__":
    main()
