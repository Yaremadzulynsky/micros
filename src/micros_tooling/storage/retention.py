"""Explicit package retention; never discard current or unresolved release artifacts."""

import json
from micros_tooling.deployment.diagnostics import connect
from micros_tooling.storage.packages import digest, read_package, require


def collect(workspace, keep=20, dry_run=True, statuses=None):
    """Keep recent rollback points and release metadata; inspect devices before deletion."""
    require(type(keep) is int and keep >= 1, "Keep at least one recent release per device.")
    protected = set()
    for path in workspace.root.rglob("history.json"):
        if path.relative_to(workspace.root).parts[0] == "build":
            continue
        history = json.loads(path.read_text())
        recent = []
        for event in reversed(history):
            if event["snapshot"] not in recent:
                recent.append(event["snapshot"])
            if len(recent) == keep:
                break
        protected.update(recent)
    for name in workspace.profiles()["devices"]:
        status = statuses[name] if statuses is not None else connect(workspace, name)[2].status()
        require(not status["activation"]["pending"] and not status.get("deployment_session"),
                "A device update is active. Retry cleanup after it finishes.")
        current = workspace.matching(status, name)
        if current:
            protected.add(current["id"])
    for path in workspace.root.rglob("attempts/*.json"):
        if path.relative_to(workspace.root).parts[0] == "build":
            continue
        attempt = json.loads(path.read_text())
        if attempt["outcome"] not in ("confirmed", "recovered", "rolled_back"):
            protected.add(attempt["release"])
    planned = []
    skipped = []
    # Complete validation before deleting anything. Older ABI artifacts are kept
    # for physical recovery rather than interpreted using today's package parser.
    for path in (workspace.root / "snapshots").glob("*/receipt.json"):
        receipt = json.loads(path.read_text())
        if receipt["id"] in protected or receipt.get("artifacts_pruned"):
            continue
        try:
            identifiers = [receipt["id"], *receipt["packages"]]
            require(all(isinstance(value, str) and len(value) == 64
                        and all(character in "0123456789abcdef" for character in value)
                        for value in identifiers), "Invalid snapshot identifiers")
            require(path.parent.name == receipt["id"] and not path.parent.is_symlink(),
                    "Invalid snapshot directory")
            if receipt.get("prune_pending"):
                # An interrupted cleanup can have removed only some packages.
                # The first pass persisted all package manifests before unlinking.
                manifests = receipt["version_manifests"]
                require(len(manifests) == len(receipt["packages"]), "Incomplete retained metadata")
                packages = []
                for expected in receipt["packages"]:
                    package = path.parent / (expected + ".msp")
                    if package.exists():
                        require(not package.is_symlink() and digest(package.read_bytes()) == expected,
                                "Damaged retained package")
                        packages.append(package)
            else:
                packages = workspace.snapshot_packages(receipt, None, verify_base=False)
                require(not any(package.is_symlink() for package in packages), "Linked snapshot package")
                manifests = [read_package(package.read_bytes())["manifest"] for package in packages]
        except (OSError, ValueError):
            skipped.append(dict(release=receipt["id"], reason="Legacy or damaged artifacts require manual review"))
            continue
        planned.append((path, receipt, packages, manifests))
    result = dict(dry_run=dry_run, keep=keep,
                  releases=[receipt["id"] for _, receipt, _, _ in planned],
                  bytes=sum(package.stat().st_size for _, _, packages, _ in planned for package in packages),
                  skipped=skipped)
    if not dry_run:
        for path, receipt, packages, manifests in planned:
            receipt["version_manifests"] = manifests
            receipt["prune_pending"] = True
            # Retain the legacy metadata field for recovery and interrupted cleanup.
            workspace.write(path.relative_to(workspace.root), receipt)
            for package in packages:
                package.unlink()
            receipt["artifacts_pruned"] = True
            receipt.pop("prune_pending", None)
            workspace.write(path.relative_to(workspace.root), receipt)
    return result
