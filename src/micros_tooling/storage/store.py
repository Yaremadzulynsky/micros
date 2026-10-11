"""Local installed-service store; enabled selection is independent of residency."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import tempfile
from micros_tooling.storage.native_image import NATIVE_HOST_TARGET
from micros_tooling.storage.packages import PackageError, admission_plan, canonical_json, digest, read_json, read_package, require, bounded_read, PACKAGE_LIMIT, VERSION, identifier

# Development store ceilings allow many small installed images but only four loaded
# instances. Persistent activation recovery is added in M6, not claimed by M4.
MAX_INSTALLED = 64
STORE_BYTES = 64 * 1024 * 1024
METADATA_BYTES = 128 * 1024


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Store:
    """Owns immutable package blobs, an installed index, and the enabled graph selection."""
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        (self.root / 'packages').mkdir(exist_ok=True, mode=0o700)
        (self.root / 'images').mkdir(exist_ok=True, mode=0o700)

    @contextmanager
    def locked(self):
        with (self.root / '.lock').open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def metadata(self, name, default):
        path = self.root / name
        if not path.exists():
            return default
        require(path.stat().st_size <= METADATA_BYTES, f'{name}: oversized metadata')
        return read_json(path.read_bytes())

    def index(self):
        index = self.metadata('installed.json', {'format': 1, 'services': {}})
        require(isinstance(index, dict) and index.get('format') == 1 and isinstance(index.get('services'), dict), 'invalid installed index')
        return index

    def selection(self):
        selection = self.metadata('enabled.json', {'format': 1, 'enabled': {}})
        require(isinstance(selection, dict) and selection.get('format') == 1 and isinstance(selection.get('enabled'), dict), 'invalid enabled selection')
        return selection

    def package(self, name, version):
        identifier(name, 'service name')
        require(isinstance(version, str) and VERSION.fullmatch(version), 'invalid selected version')
        index = self.index()
        try:
            package_digest = index['services'][name][version]
        except KeyError as error:
            raise PackageError(f'{name}@{version}: not installed') from error
        # Digest validation prevents a corrupt index from selecting an arbitrary path.
        require(isinstance(package_digest, str) and len(package_digest) == 64 and all(c in '0123456789abcdef' for c in package_digest), 'invalid package digest in index')
        data = bounded_read(self.root / 'packages' / f'{package_digest}.msp', PACKAGE_LIMIT)
        require(digest(data) == package_digest, f'{name}@{version}: stored package integrity failure')
        package = read_package(data)
        require((package['manifest']['name'], package['manifest']['version']) == (name, version), 'installed index identity mismatch')
        return package

    def install(self, data):
        package = read_package(data)
        manifest = package['manifest']
        with self.locked():
            index = self.index()
            versions = index['services'].setdefault(manifest['name'], {})
            existing = versions.get(manifest['version'])
            if existing:
                require(existing == package['sha256'], 'same name/version already identifies different immutable content')
                return {'installed': manifest['name'], 'version': manifest['version'], 'unchanged': True}
            require(sum(len(values) for values in index['services'].values()) < MAX_INSTALLED, 'installed package count capacity')
            used_bytes = sum(path.stat().st_size for path in (self.root / 'packages').glob('*.msp'))
            require(used_bytes + len(data) <= STORE_BYTES, 'installed package byte capacity')
            atomic_write(self.root / 'packages' / f'{package["sha256"]}.msp', data)
            versions[manifest['version']] = package['sha256']
            atomic_write(self.root / 'installed.json', canonical_json(index))
        return {'installed': manifest['name'], 'version': manifest['version'], 'sha256': package['sha256']}

    def plan(self, enabled=None, target=NATIVE_HOST_TARGET):
        if enabled is None:
            enabled = self.selection()['enabled']
        require(isinstance(enabled, dict), 'enabled: expected name/version mapping')
        packages = [self.package(name, version) for name, version in sorted(enabled.items())]
        return admission_plan(packages, target)

    def configure(self, enabled, target=NATIVE_HOST_TARGET):
        with self.locked():
            plan = self.plan(enabled, target)
            atomic_write(self.root / 'enabled.json', canonical_json({'format': 1, 'enabled': dict(sorted(enabled.items()))}))
            return plan

    def materialize(self, service):
        package = self.package(service['name'], service['version'])
        require(package['sha256'] == service['package_sha256'], 'package changed after admission')
        path = self.root / 'images' / f'{package["sha256"]}.mimg'
        if not path.exists() or digest(path.read_bytes()) != package['manifest']['image_sha256']:
            atomic_write(path, package['image'])
        return path
