#!/usr/bin/env python3
"""Explicit live management checks: competing clients and abandoned staging recovery.

Run only after migrating and deploying a healthy application. Stops the graph
once and intentionally leaves a session to expire; the board must restore it.
"""

import argparse
import json
from pathlib import Path
import struct
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from micros_tooling.storage.workspace import Workspace
from micros_tooling.deployment.diagnostics import connect
from micros_tooling.storage.packages import PackageError
from micros_tooling.deployment.deploy import running
from micros_tooling.communication.logs import follow_logs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="feather")
    parser.add_argument("--output", type=Path, default=ROOT / "build/usability-review/hardware")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    workspace = Workspace(ROOT / ".micros")
    _, _, owner = connect(workspace, args.device)
    _, _, competitor = connect(workspace, args.device)
    before = owner.status()
    assert before["services"] and running(before, len(before["services"]))
    with owner.deployment_session(before):
        try:
            with competitor.deployment_session(competitor.status()):
                raise AssertionError("Competing deployment session was admitted")
        except PackageError:
            pass
        assert competitor.status()["activation"] == before["activation"]
    print("PASS: competing client refused; status remained available", flush=True)

    # Deliberately omit DELETE to model a killed updater, not graceful cancellation.
    selected = owner.status()["activation"]
    owner.session_id = uuid.uuid4().hex
    owner.request("POST", "/v1/session", bytes.fromhex(selected["good_sha256"])
                  + struct.pack("<I", selected["sequence"]))
    owner.request("POST", "/v1/stop")
    assert not competitor.status()["services"]
    started = time.monotonic()
    try:
        while time.monotonic() - started < 90:
            status = competitor.status()
            if not status["deployment_session"] and running(status, len(before["services"])):
                break
            time.sleep(2)
        else:
            raise AssertionError("Abandoned staging did not recover before deadline")
        assert status["activation"]["good_sha256"] == before["activation"]["good_sha256"]
        elapsed = time.monotonic() - started
        print(f"PASS: autonomous recovery of unchanged graph after {elapsed:.1f}s", flush=True)
    finally:
        try:
            owner.request("DELETE", "/v1/session")
        except PackageError:
            pass  # Expected after successful expiry.
        owner.session_id = ""
    events = list(follow_logs(competitor))
    assert any(event["event"] == "logs" for event in events)
    report = dict(before=before, after=status, competing_client_rejected=True,
                  autonomous_recovery_seconds=elapsed, cursor_log_events=len(events))
    (args.output / "management.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
