"""Resolve exact SDK commits from the official origin into an atomic user cache."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

OFFICIAL_REPOSITORY = 'https://github.com/Yaremadzulynsky/micros.git'
REQUIRED = ('micros', 'src/micros_tooling/dispatch.py', 'src/micros_tooling/config/application.py',
            'src/micros_tooling/config/scaffold.py', 'tools/templates/application', 'tools/requirements-dev.txt')


def project_root(start=None):
    start = Path(start or Path.cwd()).resolve()
    return next((p for p in (start, *start.parents) if (p / 'micros.lock').exists()), None)


def project_revision(root):
    import tomli
    with (root / 'micros.lock').open('rb') as stream:
        lock = tomli.load(stream)
    if lock.get('format') != 1 or not isinstance(lock.get('sdk'), dict):
        raise ValueError('Unsupported micros.lock format')
    sdk = lock['sdk']
    if sdk.get('repository') != OFFICIAL_REPOSITORY:
        raise ValueError('micros.lock must use the official SDK repository: ' + OFFICIAL_REPOSITORY)
    return revision(sdk.get('revision'))


def revision(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}', value):
        raise ValueError('SDK revision must be an exact lowercase 40-character Git commit')
    return value


def git(path, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    credentials = []
    if args and args[0] == 'fetch':
        # Reuse configured authentication without importing URL rewrites,
        # arbitrary transports or hooks from the user's Git configuration.
        configured = subprocess.run(['git', '-C', str(path), 'config', '--get-urlmatch', 'credential.helper', OFFICIAL_REPOSITORY],
                                    env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for helper in configured.stdout.splitlines():
            credentials += ['-c', 'credential.helper=' + helper]
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT='0')
    result = subprocess.run(['git', *credentials, '-c', 'core.hooksPath=' + os.devnull,
                             '-c', 'http.followRedirects=false', '-c', 'protocol.allow=never',
                             '-c', 'protocol.https.allow=always', '-C', str(path), *args],
                            env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=300)
    if result.returncode:
        raise ValueError('SDK Git operation failed: ' + result.stderr.strip())
    return result.stdout.strip()


def validate(path, expected):
    if git(path, 'rev-parse', 'HEAD') != expected:
        raise ValueError('SDK revision differs from micros.lock')
    if not all((path / name).exists() for name in REQUIRED):
        raise ValueError('SDK is incomplete or lacks the application CLI contract')


@contextmanager
def cache_lock(path):
    import fcntl  # Supported host platforms: macOS and Linux.
    with path.open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def resolve(expected, *, offline=False):
    expected = revision(expected)
    override = os.environ.get('MICROS_SDK')
    if override:
        path = Path(override).expanduser().resolve()
        validate(path, expected)
        return path
    base = Path(os.environ.get('MICROS_SDK_CACHE',
                str(Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'micros/sdks'))).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    target = base / expected
    with cache_lock(base / (expected + '.lock')):
        if target.exists():
            try:
                validate(target, expected)
                if git(target, 'status', '--porcelain', '--untracked-files=no'):
                    raise ValueError('Cached SDK tracked files have changed')
                if json.loads((target / '.micros-cache.json').read_text()) != {'revision': expected, 'repository': OFFICIAL_REPOSITORY}:
                    raise ValueError('Invalid cache completion record')
                return target
            except (ValueError, OSError) as error:
                raise ValueError(f'Invalid SDK cache {target}: {error}. Move this directory aside and retry; it has not been deleted.') from error
        if offline or os.environ.get('MICROS_OFFLINE') == '1':
            raise ValueError(f'SDK {expected} is not cached; reconnect and retry without MICROS_OFFLINE=1')
        print(f'Downloading Micros SDK {expected}…', file=sys.stderr)
        with tempfile.TemporaryDirectory(prefix=expected + '.partial-', dir=base) as temporary:
            staging = Path(temporary)
            git(staging, 'init', '--quiet')
            git(staging, 'fetch', '--quiet', '--depth=1', OFFICIAL_REPOSITORY, expected)
            git(staging, 'checkout', '--quiet', '--detach', 'FETCH_HEAD')
            validate(staging, expected)
            git(staging, 'fsck', '--no-reflogs', '--full')
            (staging / '.micros-cache.json').write_text(json.dumps({'revision': expected, 'repository': OFFICIAL_REPOSITORY}))
            staging.rename(target)
        return target


def check_dependencies(path):
    """Do not quietly run old/new SDK tooling with incompatible Python packages."""
    from importlib.metadata import PackageNotFoundError, version
    from packaging.requirements import Requirement
    for line in (path / 'tools/requirements-dev.txt').read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        requirement = Requirement(line)
        if requirement.url:
            raise ValueError('SDK URL dependencies are unsupported by this CLI')
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            installed = version(requirement.name)
        except PackageNotFoundError:
            installed = None
        if installed is None or installed not in requirement.specifier:
            raise ValueError(f'SDK requires {requirement}; installed version is {installed or "missing"}. Use a compatible Micros CLI release. No dependencies were changed.')
