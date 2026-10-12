"""Operator configuration is persistent; server-backed workspace data is a cache."""
import os
import json
import re
from pathlib import Path


def config_root():
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'micros'


def application_root():
    explicit = os.environ.get('MICROS_APPLICATION_ROOT')
    if explicit:
        return Path(explicit).resolve()
    here = Path.cwd()
    return next((p for p in (here, *here.parents) if (p / 'micros.lock').is_file()), None)


def selection_file(project=None):
    project = Path(project) if project is not None else application_root()
    return project / '.micros/server.json' if project else config_root() / 'selected-server.json'


def profile_directory(name):
    from micros_tooling.storage.packages import require
    require(re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,47}', name),
            'Server name must use 1–48 lowercase letters, digits, hyphens or underscores.')
    return config_root() / 'server' if name == 'default' else config_root() / 'servers' / name


def server_description(directory):
    from micros_tooling.storage.packages import require
    from urllib.parse import urlsplit
    directory = Path(directory)
    require(all((directory / f).is_file() for f in ('client.json', 'servercert.pem', 'admin.token')),
            'Server profile is incomplete: ' + str(directory) + '. Import its operator bundle first.')
    config = json.loads((directory / 'client.json').read_text())
    require(isinstance(config, dict), 'Invalid server profile: ' + str(directory / 'client.json'))
    require(isinstance(config.get('url'), str), 'Server profile needs an HTTPS URL: ' + str(directory))
    origin = urlsplit(config['url'])
    require(origin.scheme == 'https' and origin.hostname and not origin.username
            and origin.path in ('', '/') and not origin.query and not origin.fragment,
            'Server URL must be an HTTPS origin: ' + str(directory / 'client.json'))
    origin.port  # Validate malformed or out-of-range ports before offering the profile.
    return dict(url=config['url'], cloudflare_access=config.get('cloudflare_access') is True)


def saved_servers(workspace=None):
    candidates = [('default', profile_directory('default'))]
    parent = config_root() / 'servers'
    if parent.is_dir():
        candidates += [(p.name, p) for p in sorted(parent.iterdir()) if p.is_dir()]
    if workspace is not None:
        candidates.append(('legacy', workspace.root / 'server'))
    selected = selection_file()
    if selected.is_file():
        record = json.loads(selected.read_text())
        candidates.append((record['name'], Path(record['directory'])))
    servers, seen = [], set()
    for name, directory in candidates:
        if not (directory / 'client.json').is_file() or directory.resolve() in seen:
            continue
        # A broken profile must not prevent selecting another usable server.
        try:
            description = server_description(directory)
        except (OSError, ValueError) as error:
            description = dict(error=str(error))
        servers.append(dict(name=name, directory=str(directory.resolve()), **description))
        seen.add(directory.resolve())
    return servers


def select_server(name, *, directory=None, project=None):
    from micros_tooling.storage.store import atomic_write
    directory = Path(directory) if directory is not None else profile_directory(name)
    server_description(directory)
    # Only a local reference is saved; credentials stay in the operator directory.
    atomic_write(selection_file(project), json.dumps(dict(name=name, directory=str(directory.resolve()))).encode())
    return directory.resolve()


def explicit_selection(project=None):
    return bool(os.environ.get('MICROS_CLIENT_DIR') or os.environ.get('MICROS_SERVER')
                or selection_file(project).is_file())


def operator_directory(workspace=None, *, project=None):
    explicit = os.environ.get('MICROS_CLIENT_DIR')
    if explicit:
        return Path(explicit).expanduser()
    name = os.environ.get('MICROS_SERVER')
    if name:
        return profile_directory(name)
    selected = selection_file(project)
    if selected.is_file():
        from micros_tooling.storage.packages import require
        record = json.loads(selected.read_text())
        directory = Path(record['directory'])
        require(directory.is_absolute(), 'Saved server directory must be absolute: ' + str(selected))
        # Keep a missing selection selected; never fall back to another server.
        return directory
    # Explicit/legacy state remains supported for recovery and local server administration.
    if workspace is not None and (workspace.root / 'server/client.json').is_file():
        return workspace.root / 'server'
    return profile_directory('default')


def application_cache(root):
    import hashlib
    directory = operator_directory(project=root)
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
    source = Path(source).expanduser()
    server_description(source)
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
