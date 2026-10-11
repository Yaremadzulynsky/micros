"""Cursor-based diagnostic streaming with explicit reboot and loss reporting."""

import codecs
import time
import http.client
import ssl
from micros_tooling.storage.packages import require
from micros_tooling.communication.remote import RemoteRejected


def follow_logs(remote, follow=False):
    """Yield exact byte chunks; repeated text is preserved instead of deduplicated."""
    cursor, boot = 0, None
    snapshot_end = None
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    while True:
        try:
            reply = remote.request("GET", f"/v1/log-stream?cursor={cursor}")
        except RemoteRejected as error:
            # Cursor reads are safe to retry after a relay timeout or temporary
            # device unavailability. Never retry authentication/protocol failures.
            if not follow or error.status not in (409, 503, 504):
                raise
            yield dict(event="reconnecting", message=str(error))
            time.sleep(2)
            continue
        except ssl.SSLCertVerificationError:
            raise
        except (OSError, http.client.HTTPException) as error:
            if not follow:
                raise
            yield dict(event="reconnecting", message=str(error))
            time.sleep(2)
            continue
        require(isinstance(reply.get("boot_id"), str) and type(reply.get("next")) is int
                and type(reply.get("start")) is int and type(reply.get("lost")) is int,
                "Invalid log cursor response")
        if boot is not None and boot != reply["boot_id"]:
            yield dict(event="reboot", boot_id=reply["boot_id"])
            cursor, boot = 0, reply["boot_id"]
            snapshot_end = None
            decoder.reset()
            continue
        boot = reply["boot_id"]
        if snapshot_end is None:
            snapshot_end = reply["end"]
        data = bytes.fromhex(reply["data_hex"])
        require(reply["next"] == reply["start"] + len(data) and reply["start"] >= cursor
                and reply["lost"] == reply["start"] - cursor, "Inconsistent log cursor response")
        cursor = reply["next"]
        if reply["lost"]:
            decoder.reset()
            yield dict(event="lost", bytes=reply["lost"])
        if data:
            yield dict(event="logs", boot_id=boot, cursor=cursor, logs=decoder.decode(data))
            if not follow and cursor >= snapshot_end:
                return
            continue  # Drain buffered chunks before polling again.
        if not follow:
            return
        time.sleep(1)
