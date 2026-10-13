#!/usr/bin/env python3
"""Authenticated remote service deployment, status and diagnostics over pinned TLS."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from micros_tooling.communication.remote import Remote

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--host", required=True)
parser.add_argument(
    "--certificate", type=Path, default=Path("build/private/servercert.pem")
)
parser.add_argument(
    "--token-file", type=Path, default=Path("build/private/management.token")
)
parser.add_argument(
    "--firmware", type=Path, default=Path("build/esp32-runtime/micros_runtime.elf")
)
parser.add_argument("action", choices=["deploy", "status", "logs", "stop", "reboot"])
parser.add_argument("packages", type=Path, nargs="*")
args = parser.parse_args()
remote = Remote(args.host, args.certificate, args.token_file)
if args.action == "deploy":
    result = remote.deploy(args.packages, args.firmware)
elif args.action == "status":
    result = remote.status()
elif args.action == "logs":
    result = remote.request("GET", "/v1/logs")
else:
    with remote.deployment_session(remote.status()):
        result = remote.request("POST", "/v1/pause" if args.action == "stop" else "/v1/" + args.action)
print(result if isinstance(result, str) else json.dumps(result, indent=2))
