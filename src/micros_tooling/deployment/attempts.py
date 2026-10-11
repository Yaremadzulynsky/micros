"""Durable host-side deployment progress and observation after client interruption."""

from datetime import datetime, timezone
from pathlib import Path
import uuid
import time
from micros_tooling.deployment.deploy import deploy, running


def recorded_deploy(workspace, name, receipt, remote, packages, firmware, **options):
    record = dict(id=uuid.uuid4().hex, release=receipt["id"], banks=receipt["banks"],
                  started_at=datetime.now(timezone.utc).isoformat(), phase="prepared", outcome="pending")
    progress = options.pop("progress", lambda *args: None)
    stopped_at = None

    def save():
        workspace.write(Path("devices") / name / "attempts" / (record["id"] + ".json"), record)
        workspace.write(Path("devices") / name / "attempt.json", record)

    def emit(phase, message):
        nonlocal stopped_at
        record["phase"] = phase
        record["phase_at"] = datetime.now(timezone.utc).isoformat()
        if phase == "stop":
            stopped_at = time.monotonic()
        save()
        progress(phase, message)

    save()
    try:
        result = deploy(remote, packages, firmware, progress=emit, **options)
    except BaseException as error:
        record["outcome"] = getattr(error, "outcome", "unknown")
        save()
        raise
    record["outcome"] = "confirmed"
    result["stop_to_confirmation_seconds"] = round(time.monotonic() - stopped_at, 3) if stopped_at else 0
    record["stop_to_confirmation_seconds"] = result["stop_to_confirmation_seconds"]
    save()
    return result


def observe_attempt(workspace, name, status):
    """Report live evidence separately from the durable last-known phase."""
    attempt = workspace.read(Path("devices") / name / "attempt.json")
    if not attempt:
        return None
    result = dict(attempt)
    selection = status["activation"]
    expected = attempt["banks"].get(str(selection["good"]))
    if selection["pending"]:
        result["observed"] = "trial pending; observe before retrying"
    elif expected == selection["good_sha256"] and status["services"] and running(status, len(status["services"])):
        result["observed"] = "requested release is running"
    elif status["services"] and running(status, len(status["services"])):
        result["observed"] = "another selected release is running; inspect history"
    else:
        result["observed"] = "selected services are not running; inspect logs, then recover"
    return result
