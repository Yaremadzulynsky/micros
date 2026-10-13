"""Verified directory bundles for private recovery state and compiled releases."""

import json
from pathlib import Path
from micros_tooling.storage.packages import digest, read_package, require, identifier
from micros_tooling.storage.store import atomic_write


def write_bundle(destination, files, kind):
    """Export to a new private directory; a manifest is written last as the completion marker."""
    destination = Path(destination).resolve()
    require(not destination.exists(), "Export destination already exists; choose a new directory.")
    destination.mkdir(parents=True, mode=0o700)
    manifest = dict(format=1, kind=kind, files={})
    for name, data in files.items():
        atomic_write(destination / name, data)
        manifest["files"][name] = digest(data)
    atomic_write(destination / "bundle.json", json.dumps(manifest, indent=2).encode())
    return dict(directory=str(destination), kind=kind, files=len(files))


def read_bundle(directory, kind):
    """Validate all paths and bytes before a caller writes anything to the workspace."""
    directory = Path(directory).resolve()
    manifest = json.loads((directory / "bundle.json").read_text())
    require(manifest.get("format") == 1 and manifest.get("kind") == kind, "Wrong bundle format or kind.")
    files = {}
    for name, expected in manifest["files"].items():
        path = Path(name)
        require(not path.is_absolute() and ".." not in path.parts and path.name not in ("bundle.json", ".lock"),
                "Unsafe bundle path.")
        target = directory / path
        require(target.resolve().is_relative_to(directory) and not any(
            parent.is_symlink() for parent in [target, *target.parents] if parent != directory),
            "Bundle must contain regular files, not symbolic links.")
        data = target.read_bytes()
        require(digest(data) == expected, "Bundle file is damaged: " + name)
        files[name] = data
    return files


def export_state(workspace, destination):
    destination = Path(destination).resolve()
    require(not destination.is_relative_to(workspace.root.resolve()),
            "Private backup destination must be outside the workspace state directory.")
    files = {}
    # SQLite's online backup API includes committed WAL transactions atomically.
    # Copying live db/WAL files separately could create an unusable recovery bundle.
    registry = workspace.root / "server/registry.sqlite"
    if registry.exists():
        import sqlite3
        import tempfile
        require(not registry.is_symlink(), "Server registry must be a regular file.")
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = Path(temporary) / "registry.sqlite"
            source = sqlite3.connect(registry.as_uri() + "?mode=ro", uri=True)
            target = sqlite3.connect(snapshot)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
            files["server/registry.sqlite"] = snapshot.read_bytes()
    for path in workspace.root.rglob("*"):
        relative = path.relative_to(workspace.root)
        if str(relative) in ("server/registry.sqlite", "server/registry.sqlite-wal", "server/registry.sqlite-shm"):
            continue
        if relative.parts[0] in ("build", ".locks") or relative.name == ".lock":
            continue
        require(not path.is_symlink(), "State contains a symbolic link; refusing private export.")
        if path.is_file():
            files[str(relative)] = path.read_bytes()
    return write_bundle(destination, files, "private-state")


def import_state(workspace, source):
    files = read_bundle(source, "private-state")
    require("devices.json" in files, "Backup contains no device profiles.")
    profiles = json.loads(files["devices.json"])
    require(isinstance(profiles.get("devices"), dict), "Backup device index is invalid.")
    require(profiles.get("default") is None or profiles["default"] in profiles["devices"],
            "Backup default device is invalid.")
    for name, profile in profiles["devices"].items():
        identifier(name, "backup device name")
        require(isinstance(profile, dict) and isinstance(profile.get("host"), str)
                and profile.get("transport") in ("native", "docker"), "Invalid backup device profile.")
        for required in ("certificate.pem", "token", "firmware.elf"):
            require(f"devices/{name}/{required}" in files, "Backup is missing paired artifacts for " + name)
        for environment, filename in profile.get("environments", {}).items():
            identifier(environment, "backup environment name")
            require(filename == f"environments/{environment}.toml"
                    and f"devices/{name}/{filename}" in files, "Invalid backup environment path.")
        if profile.get("board"):
            require(profile["board"] == "board.toml" and f"devices/{name}/board.toml" in files,
                    "Backup is missing its saved board definition.")
        if profile.get("relay"):
            require(all(f"devices/{name}/{filename}" in files for filename in ("relay-ca.pem", "relay-admin.token")),
                    "Backup is missing relay operator credentials.")
    for path in workspace.root.rglob("*"):
        require(not path.is_symlink(), "Import destination contains a symbolic link.")
        if path.is_file() and path.name != ".lock":
            require(files.get(str(path.relative_to(workspace.root))) == path.read_bytes(),
                    "Import requires empty state or an interrupted identical import; use MICROS_STATE_DIR.")
    # Complete validation precedes writes; publish the device index last.
    for name in sorted(files, key=lambda name: name == "devices.json"):
        atomic_write(workspace.root / name, files[name])
    return dict(imported=True, files=len(files))


def export_release(workspace, name, release, destination):
    history = workspace.history(name)
    matches = {event["snapshot"] for event in history if not release or event["snapshot"].startswith(release)}
    if not release and history:
        matches = {history[-1]["snapshot"]}
    require(len(matches) == 1, "Select exactly one recorded release using its full ID or unique prefix.")
    snapshot = matches.pop()
    receipt = workspace.read(Path("snapshots") / snapshot / "receipt.json")
    paths = workspace.snapshot_packages(receipt, workspace.files(name)[2])
    return write_bundle(destination, {"receipt.json": json.dumps(receipt).encode(),
        **{path.name: path.read_bytes() for path in paths}}, "release")


def release_packages(source, firmware):
    files = read_bundle(source, "release")
    receipt = json.loads(files["receipt.json"])
    require(receipt["firmware_sha256"] == digest(Path(firmware).read_bytes()),
            "Release requires a different base. Select a compatible device or migrate physically.")
    paths = []
    for value in receipt["packages"]:
        name = value + ".msp"
        require(name in files and digest(files[name]) == value, "Release package hash mismatch.")
        read_package(files[name])
        paths.append(Path(source) / name)
    return paths


def export_packages(packages, firmware, destination):
    """Create a reviewable release before the first device deployment."""
    import tempfile
    from micros_tooling.platforms.esp32.device import prepare
    from micros_tooling.deployment.deploy import graph_digest
    from micros_tooling.storage.workspace import Workspace
    banks = {}
    for bank in (0, 1):
        images, graph, _ = prepare(packages, firmware, bank)
        banks[bank] = dict(digest=graph_digest(images, graph))
    with tempfile.TemporaryDirectory() as temporary:
        receipt = Workspace(temporary).snapshot(packages, dict(banks=banks), firmware)
    return write_bundle(destination, {"receipt.json": json.dumps(receipt).encode(),
        **{digest(Path(path).read_bytes()) + ".msp": Path(path).read_bytes() for path in packages}}, "release")
