"""Deployment state machine shared by terminal and future graphical clients."""

import hashlib
import http.client
import struct
import time

from micros_tooling.platforms.esp32.device import prepare
from micros_tooling.storage.packages import PackageError, require
from micros_tooling.deployment.identity import verify_base

NO_BANK = 0xFFFFFFFF  # The device journal's uint32 sentinel for no confirmed graph.
HEALTH_TIMEOUT_SECONDS = (
    60  # Two trials, Wi-Fi reconnection and five-second device health window.
)


class DeploymentError(PackageError):
    """A failed attempt with an explicit recovery outcome, suitable for a human-facing UI."""

    def __init__(self, message, outcome):
        super().__init__(message)
        self.outcome = outcome


def graph_digest(images, graph):
    """Match firmware identity: complete graph, then images in its service-record order."""
    identity = hashlib.sha256(graph)
    service_count = struct.unpack_from("<I", graph, 12)[0]
    # MRG2: five header words, four four-word channels, then nine-word service records.
    for index in range(service_count):
        slot = struct.unpack_from("<I", graph, (5 + 16 + index * 9) * 4)[0]
        identity.update(images[slot])
    return identity.hexdigest()


def running(status, count):
    return len(status["services"]) == count and all(
        service["state"] == "Running" and service["result"] == 0
        for service in status["services"]
    )


def inspect_deployment(remote, packages, firmware):
    """Validate both bank layouts and fetch status before any device mutation."""
    require(packages, "Choose an application containing at least one service.")
    before = remote.status()
    verify_base(before, firmware)
    banks = {}
    for bank in (0, 1):
        images, graph, plan = prepare(packages, firmware, bank)
        banks[bank] = dict(
            images=images, graph=graph, digest=graph_digest(images, graph)
        )
    require(
        not before["activation"]["pending"],
        "Another activation is still being checked. Run micros status before retrying.",
    )
    good = before["activation"]["good"]
    require(good in (0, 1, NO_BANK), "Device returned an invalid selected bank.")
    unchanged = (
        good != NO_BANK and before["activation"]["good_sha256"] == banks[good]["digest"]
    )
    return dict(
        before=before,
        banks=banks,
        plan=plan,
        unchanged=unchanged,
        candidate=0 if good == NO_BANK else 1 - good,
    )


def deploy(
    remote, packages, firmware, **options
):
    """Hold the board's selection lease across staging, activation and recovery."""
    prepared = options.pop("prepared", None) or inspect_deployment(remote, packages, firmware)
    if hasattr(remote, "deployment_session"):
        with remote.deployment_session(prepared["before"]):
            return _deploy(remote, packages, firmware, prepared=prepared, **options)
    # Pure in-process test transports have no HTTP session mechanism.
    return _deploy(remote, packages, firmware, prepared=prepared, **options)


def _deploy(
    remote,
    packages,
    firmware,
    *,
    progress=None,
    force=False,
    prepared=None,
    clock=time.monotonic,
    sleep=time.sleep,
):
    """Commit verified content, observe health, and recover a stopped good graph on staging failure."""
    emit = progress or (lambda phase, message: None)
    inspection = prepared or inspect_deployment(remote, packages, firmware)
    before, plan = inspection["before"], inspection["plan"]
    previous = before["activation"]
    # Preflight/build/history may take time. Refuse an observed competing activation before STOP.
    current = remote.status()
    require(current.get("identity") == before.get("identity"),
            "Device identity changed during preparation. Refusing deployment.")
    require(
        current["activation"] == previous,
        "Device selection changed during preparation. Run deploy again to refresh the plan.",
    )
    if inspection["unchanged"] and not force:
        if not running(current, len(plan["services"])):
            emit("restart", "Starting the already-installed application")
            remote.request(
                "POST",
                f'/v1/activate?bank={previous["good"]}',
                bytes.fromhex(previous["good_sha256"]),
            )
            current = remote.status()
            require(
                running(current, len(plan["services"])),
                "The selected application did not start.",
            )
        emit("unchanged", "Already deployed and running; no flash writes needed")
        return dict(
            activated_bank=previous["good"], plan=plan, status=current, unchanged=True
        )
    candidate = inspection["candidate"]
    images, graph, expected = (
        inspection["banks"][candidate][key] for key in ("images", "graph", "digest")
    )
    stopped = False
    activation_sent = False
    try:
        # A lost STOP response can still mean the board stopped; enable recovery before sending it.
        if force or not current.get("selective_deploy"):
            stopped = True
            emit("stop", "Stopping services briefly for the update")
            remote.request("POST", "/v1/stop")
        else:
            emit("stage", "Staging the candidate while current services keep running")
        for index, (slot, image) in enumerate(sorted(images.items()), 1):
            emit(
                "upload",
                f"Transferring service {index}/{len(images)} ({len(image)} bytes)",
            )
            remote.request("PUT", f"/v1/image?bank={candidate}&slot={slot}", image)
        emit("stage", "Writing the complete application configuration")
        remote.request("PUT", f"/v1/graph?bank={candidate}", graph)
        emit("activate", "Activating the update; compatible unchanged services retain their instances"
             if current.get("selective_deploy") else "Activating the update")
        activation_sent = True
        try:
            remote.request(
                "POST", f"/v1/activate?bank={candidate}", bytes.fromhex(expected)
            )
        except (OSError, http.client.HTTPException):
            pass  # The board can reboot before answering; status decides the outcome.
        emit("health", "Waiting for runtime liveness confirmation and any reconnection")
        deadline = clock() + HEALTH_TIMEOUT_SECONDS
        while clock() < deadline:
            try:
                status = remote.status()
            except (OSError, http.client.HTTPException):
                sleep(0.5)
                continue
            selection = status["activation"]
            if not selection["pending"]:
                if (
                    selection["good"] == candidate
                    and selection["good_sha256"] == expected
                ):
                    require(
                        running(status, len(plan["services"])),
                        "Content was selected but its services are not running. Run micros status.",
                    )
                    emit("confirmed", "Update confirmed; all services are running")
                    return dict(
                        activated_bank=candidate,
                        plan=plan,
                        status=status,
                        unchanged=False,
                    )
                if selection["good_sha256"] == previous["good_sha256"]:
                    if not running(status, len(before["services"])):
                        if current.get("selective_deploy"):
                            sleep(0.5)
                            continue
                        raise PackageError(
                            "Activation did not start; the previous application is stopped."
                        )
                    raise DeploymentError(
                        "The update did not pass activation; the previous application is running.",
                        "rolled_back",
                    )
                raise DeploymentError(
                    "Device selection changed unexpectedly. Run micros status.",
                    "changed",
                )
            sleep(0.5)
        raise DeploymentError(
            "The device has not confirmed the update yet. Run micros status before retrying; "
            "do not assume the update failed.",
            "unknown",
        )
    except (
        PackageError,
        OSError,
        http.client.HTTPException,
        KeyboardInterrupt,
    ) as error:
        if isinstance(error, DeploymentError) and error.outcome in (
            "rolled_back",
            "changed",
            "unknown",
        ):
            raise
        if stopped:
            emit(
                "recover", "Checking whether the previous application can be restarted"
            )
            try:
                status = remote.status()
                selection = status["activation"]
                same_good = (
                    selection["good"] == previous["good"]
                    and selection["good_sha256"] == previous["good_sha256"]
                )
                if (
                    same_good
                    and not selection["pending"]
                    and previous["good"] != NO_BANK
                ):
                    # Never restart a bank while a trial is pending or after another selection won.
                    remote.request(
                        "POST",
                        f'/v1/activate?bank={previous["good"]}',
                        bytes.fromhex(previous["good_sha256"]),
                    )
                    recovered = remote.status()
                    if (
                        recovered["activation"]["good_sha256"]
                        == previous["good_sha256"]
                        and not recovered["activation"]["pending"]
                        and recovered["services"]
                        and running(
                            recovered,
                            len(before["services"]) or len(recovered["services"]),
                        )
                    ):
                        raise DeploymentError(
                            "Update interrupted. The previous application is running again. "
                            "You can retry deploy. Cause: " + str(error),
                            "recovered",
                        ) from error
            except DeploymentError:
                raise
            except (PackageError, OSError, http.client.HTTPException):
                pass
        if not stopped and not activation_sent and current.get("selective_deploy"):
            try:
                observed = remote.status()
                if (observed["activation"] == previous and running(observed, len(before["services"]))
                        and observed.get("service_boot") == before.get("service_boot")):
                    raise DeploymentError("Staging interrupted; the previous application is still running. Cause: "
                                          + str(error), "preserved") from error
            except DeploymentError:
                raise
            except (PackageError, OSError, http.client.HTTPException):
                pass
        phase = "activation" if activation_sent else "transfer"
        raise DeploymentError(
            f"Update interrupted during {phase}. Device state is unconfirmed. "
            "Run micros status, then micros recover when it is reachable. Cause: "
            + str(error),
            "unknown",
        ) from error
