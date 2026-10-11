"""Operator configuration is persistent; server-backed workspace data is a cache."""
import os
from pathlib import Path


def operator_directory(workspace=None):
    explicit = os.environ.get('MICROS_CLIENT_DIR')
    if explicit:
        return Path(explicit).expanduser()
    # Explicit/legacy state remains supported for recovery and local server administration.
    if workspace is not None and (workspace.root / 'server/client.json').is_file():
        return workspace.root / 'server'
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'micros/server'


def application_cache(root):
    import hashlib
    directory = operator_directory()
    config = directory / 'client.json'
    # Isolate caches when switching servers, including a replaced TLS identity.
    identity = config.read_bytes() if config.exists() else str(directory).encode()
    certificate = directory / 'servercert.pem'
    if certificate.exists():
        identity += certificate.read_bytes()
    key = hashlib.sha256(identity).hexdigest()[:16]
    return Path(root) / 'build/micros-client' / key


def import_operator(source, destination=None):
    """Copy only client authentication; leave all legacy server/device state intact."""
    from micros_tooling.storage.store import atomic_write
    from micros_tooling.storage.packages import require
    source = Path(source)
    destination = Path(destination) if destination else operator_directory()
    files = {name: (source / name).read_bytes()
             for name in ('client.json', 'servercert.pem', 'admin.token')}
    for name, data in files.items():
        target = destination / name
        require(not target.exists() or target.read_bytes() == data,
                'Existing operator configuration differs: ' + str(target))
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, data in files.items():
        atomic_write(destination / name, data)
    return destination
