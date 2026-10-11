"""Verified whole-base A/B updates using the board's inactive app partition."""

import hashlib
import time
import sys
from pathlib import Path
from micros_tooling.storage.packages import require
from micros_tooling.communication.remote import RemoteRejected
from micros_tooling.platforms.embedded.transport import SerialResponseError
from .build import base_info


class ChunkRejected(ValueError):
    """An explicit chunk rejection must be reconciled before retrying."""


def update(remote, firmware, image=None, dry_run=False, chunked=False):
    firmware = Path(firmware)
    info = base_info(firmware)
    data = Path(image or firmware.with_suffix(".bin")).read_bytes()
    require(
        data == firmware.with_suffix(".bin").read_bytes(),
        "BIN differs from the verified ELF sibling",
    )
    before = remote.status()
    ota = before.get("base_ota", {})
    require(
        ota.get("version") == 1 and not ota.get("pending") and not before["pending"],
        "Install A/B selector over USB and wait for trials to finish",
    )
    slot = 1 - ota["slot"]
    digest = hashlib.sha256(data).hexdigest()
    require(256 <= len(data) <= ota["slot_bytes"], "Base does not fit inactive slot")
    if dry_run:
        return dict(dry_run=True, slot=slot, bytes=len(data), capacity=ota["slot_bytes"])
    network = hasattr(remote, "relay")
    print(
        f"Uploading verified base ({len(data)} bytes) for slot {slot}",
        file=sys.stderr,
        flush=True,
    )
    if network and not chunked:
        remote.relay.request("POST", "/v1/base-image/" + digest, data)
    print("Preparing inactive slot", file=sys.stderr, flush=True)
    remote.request(f"BASE_BEGIN {slot} {len(data)} {digest}")
    if network and not chunked:
        print("Starting authenticated board download", file=sys.stderr, flush=True)
        try:
            remote.request("BASE_FETCH " + digest)
        except (OSError, TimeoutError, RemoteRejected):
            pass  # Fetch may have been accepted; inspect outcome.
    else:
        for offset in range(0, len(data), 256):
            chunk = data[offset : offset + 256]
            chunk += b"\xff" * (-len(chunk) % 64)
            # Firmware accepts a duplicate chunk only if its flash bytes match.
            # Recheck the unchanged base and staging slot before any retry.
            for attempt in range(3):
                try:
                    response = remote.request(f"BASE_WRITE {offset} {chunk.hex()}", allow_error=True)
                    if response.get('result') == -1:
                        raise ChunkRejected('Firmware chunk was rejected; inspect status before another update.')
                    require(response.get('result') == 0, 'Firmware chunk write failed.')
                    break
                except (OSError, TimeoutError, SerialResponseError, RemoteRejected, ChunkRejected) as error:
                    if isinstance(error, RemoteRejected) and error.status not in (502, 503, 504):
                        raise
                    if attempt == 2:
                        raise
                    observed = remote.status()
                    require(observed['base_sha256'] == before['base_sha256'] and
                            observed.get('base_ota', {}).get('staging') == slot and
                            observed['base_ota'].get('written') in (offset, min(offset + len(chunk), len(data))),
                            'Base upload was interrupted; inspect status before starting another update.')
                    time.sleep(.2)
            if offset % 16384 == 0:
                print(f"Base upload: {offset + len(chunk)}/{len(data)} bytes", file=sys.stderr, flush=True)
        try:
            remote.request("BASE_ACTIVATE")
        except (OSError, TimeoutError):
            pass  # Resolve outcome; never replay activation.
    print('Waiting for the updated firmware to reconnect and confirm', file=sys.stderr, flush=True)
    deadline = time.monotonic() + 420
    observed_state = None
    while time.monotonic() < deadline:
        time.sleep(3)
        try:
            status = remote.status()
        except (OSError, TimeoutError, ValueError, RemoteRejected):
            continue
        current = status.get("base_ota", {})
        state = (current.get('slot'), current.get('pending'), current.get('staging'))
        if state != observed_state:
            print(f"Firmware slot {current.get('slot')}; " +
                  ('trial awaiting console connection' if current.get('pending') else
                   'transfer in progress' if current.get('staging', 0xFFFFFFFF) < 2 else
                   'boot confirmed' if current.get('slot') == slot and status['base_sha256'] == info['hash'].hex() else
                   'previous firmware remains selected'),
                  file=sys.stderr, flush=True)
            observed_state = state
        if (
            current.get("slot") == slot
            and status["base_sha256"] == info["hash"].hex()
            and not current.get("pending")
        ):
            return dict(confirmed=True, status=status, firmware=str(firmware.resolve()))
        if (
            not current.get("pending")
            and current.get("staging", 0xFFFFFFFF) > 1
            and current.get("slot") == ota["slot"]
        ):
            raise ValueError(
                "Base update ended without confirming the new slot; previous base remains selected"
            )
    raise TimeoutError("Base outcome unknown; inspect status before another update")
