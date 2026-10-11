"""Plan-owned generated output. Validation never publishes partial artifacts."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

from micros_tooling.storage.packages import require

MANIFEST = '.micros-generated.json'


def service_directory(project, contract):
    project, contract = Path(project).resolve(), Path(contract).resolve()
    try:
        relative = contract.parent.relative_to(project / 'services')
        return project / 'build/services' / relative
    except ValueError:
        # Two dependencies can both have a directory named sensor.
        try: identity = str(contract.relative_to(project))
        except ValueError: identity = str(contract)
        suffix = hashlib.sha256(identity.encode()).hexdigest()[:12]
        return project / 'build/services' / (contract.parent.name + '-' + suffix)


def publish(plans):
    """Preflight all owners, stage all bytes, then publish with rollback on error.

Each plan is (directory, owner identity, filename -> text). The manifest is a
disposable record of generated ownership, not an input to declaration semantics.
"""
    merged = {}
    for directory, owner, files in plans:
        directory = Path(directory).resolve()
        if directory in merged:
            require(merged[directory] == (owner, files), f'Conflicting generated owners: {directory}')
        merged[directory] = (owner, files)
    writes, removals, before = {}, set(), {}
    for directory, (owner, files) in merged.items():
        manifest = directory / MANIFEST
        previous = json.loads(manifest.read_text()) if manifest.exists() else None
        require(previous is None or previous.get('owner') == owner,
                f'{directory}: output belongs to {previous.get("owner") if previous else "another contract"}; select a separate output directory')
        old = set(previous.get('files', [])) if previous else set()
        require(all(isinstance(n, str) and Path(n).name == n for n in old), f'Invalid output manifest: {manifest}')
        for name, content in files.items():
            require(Path(name).name == name and name != MANIFEST, f'Invalid artifact filename: {name}')
            path = directory / name
            require(not path.is_symlink(), f'Refusing generated symlink: {path}')
            require(not path.exists() or path.read_bytes().startswith((b'/* Generated from ', b'// Generated from ')),
                    f'Refusing to overwrite non-generated file: {path}')
            writes[path] = content.encode()
        for name in old - set(files):
            path = directory / name
            require(not path.is_symlink(), f'Refusing generated symlink: {path}')
            if path.exists() and path.read_bytes().startswith((b'/* Generated from ', b'// Generated from ')): removals.add(path)
        writes[manifest] = (json.dumps(dict(format=1, owner=owner, files=sorted(files)), sort_keys=True, indent=2) + '\n').encode()
    writes = {p:b for p,b in writes.items() if not p.exists() or p.read_bytes() != b}
    staged = {}
    try:
        for path, data in writes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            before[path] = path.read_bytes() if path.exists() else None
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.micros-stage-', delete=False) as stream:
                staged[path] = Path(stream.name)
                stream.write(data)
        for path in removals: before[path] = path.read_bytes()
        for path, temporary in staged.items(): os.replace(temporary, path)
        for path in removals: path.unlink()
    except Exception:
        from micros_tooling.storage.store import atomic_write
        for path, original in before.items():
            if original is None: path.unlink(missing_ok=True)
            else: atomic_write(path, original)
        raise
    finally:
        for temporary in staged.values(): temporary.unlink(missing_ok=True)
    return sorted(writes)


def build_inputs(service):
    """Explicit generated build inputs shared by every platform backend."""
    spec = service.get('_interface')
    if not spec: return [], []
    directory = Path(service.get('_contract', spec)['directory']) / 'generated'
    manifest = directory / MANIFEST
    require(manifest.is_file(), f'Generate service interfaces before building: {directory}')
    files = json.loads(manifest.read_text())['files']
    # Lifecycle, command and unit adapters are already in the resolved sources.
    sources = [directory / n for n in files if n.endswith('.pb.c') or n == spec['name'] + '_ipc.c']
    return sources, [directory]
