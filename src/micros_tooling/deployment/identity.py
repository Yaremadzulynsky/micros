"""Verify the authenticated board's base before preparing a native deployment."""

from pathlib import Path
from micros_tooling.storage.deployment import GRAPH_VERSION
from micros_tooling.storage.packages import ABI_MAJOR, ABI_REVISION, digest, require


def verify_base(status, firmware):
    """Reject unknown/incorrect bases before STOP; never infer identity from slot addresses."""
    identity = status.get("identity")
    require(isinstance(identity, dict),
            "This base cannot report its identity. Use USB base migration before deploying; no services were stopped.")
    require(identity.get("abi_major") == ABI_MAJOR
            and identity.get("abi_revision") == ABI_REVISION
            and identity.get("graph_format") == GRAPH_VERSION,
            "Device ABI/graph format is incompatible with this checkout. Migrate the base over USB.")
    paired_hash = digest(Path(firmware).read_bytes())
    require(identity.get("base_sha256") == paired_hash,
            f"Paired base does not match the flashed device: board reports {identity.get('base_sha256')}, "
            f"paired ELF {firmware} is {paired_hash}. Restore the matching ELF and sdkconfig "
            "from the board’s original build, or migrate over USB; no services were stopped.")
    require(isinstance(identity.get("device_id"), str) and len(identity["device_id"]) == 12,
            "Device returned an invalid hardware identity.")
    return identity
