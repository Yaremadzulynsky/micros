"""Public flash inventory from exact-base artifacts and reconstructed graph hashes.

This is stored-image accounting, not a scan of erased bytes or runtime allocation.
Only the selected services are attributed; other flash contents remain unknown.
"""
from collections import OrderedDict
import json
from pathlib import Path
import tempfile
import threading
import struct
from elftools.common.exceptions import ELFError
from micros_tooling.storage.artifacts import unpack, validate_base
from micros_tooling.storage.flash_layout import partitions
from micros_tooling.storage.packages import read_package, PackageError


class FlashInventory:
    def __init__(self, registry):
        self.registry = registry
        self.cache = OrderedDict()
        self.lock = threading.Lock()

    def describe(self, status):
        # Embedded telemetry already supplies its versioned physical layout and
        # stored image sizes. An absent ESP32 artifact must not erase that data.
        reported = status.get('flash')
        if isinstance(reported, dict) and reported.get('partitions'):
            return reported
        base = status.get('identity', {}).get('base_sha256')
        activation = status.get('activation', {})
        total = status.get('board', {}).get('flash_mb')
        if type(total) is not int or not 0 < total <= 16:
            return None
        result = dict(total_bytes=total * 1024 * 1024, source='board_capacity', partitions=[])
        with self.registry.changed:
            # Old registries can be opened before artifact initialization.
            if not self.registry.db.execute("SELECT 1 FROM sqlite_master WHERE name='artifacts'").fetchone():
                return result
            revision = self.registry.db.execute('SELECT count(*),coalesce(sum(length(body)),0) FROM artifacts').fetchone()
        key = (base, activation.get('good_sha256'), activation.get('good'),
               bool(activation.get('pending')), total, *revision)
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            try:
                result = self._describe(status, result)
            except (ValueError, KeyError, TypeError, OSError, UnicodeError, struct.error, ELFError):
                # Missing or incompatible archived data must not break the console.
                pass
            self.cache[key] = result
            while len(self.cache) > 32:
                self.cache.popitem(last=False)
        return result

    def _describe(self, status, result):
        base = status['identity']['base_sha256']
        with self.registry.changed:
            row = self.registry.db.execute("SELECT body FROM artifacts WHERE kind='bases' AND key=?", (base,)).fetchone()
        if not row:
            return result
        files = unpack(row[0])
        validate_base(base, files)
        if 'partition-table.bin' not in files:
            return result
        layout = partitions(files['partition-table.bin'])
        if any(p['offset'] + p['size'] > result['total_bytes'] for p in layout):
            return result
        result.update(partitions=layout, source='base_build_artifact')
        activation = status.get('activation', {})
        services = next((p for p in layout if p['name'] == 'services'), None)
        if not services or activation.get('pending') or activation.get('good') not in (0, 1):
            return result
        bank = activation['good']
        with self.registry.changed:
            rows = self.registry.db.execute("SELECT body FROM artifacts WHERE kind='releases' ORDER BY rowid DESC").fetchall()
        for row in rows:
            archived = unpack(row[0])
            receipt = json.loads(archived['receipt.json'])
            if receipt['firmware_sha256'] != base or receipt['banks'].get(str(bank)) != activation.get('good_sha256'):
                continue
            from micros_tooling.platforms.esp32.device import prepare
            from micros_tooling.deployment.deploy import graph_digest
            # Reconstruct the real graph and resolve physical slots from the exact ELF.
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                firmware = path / 'firmware.elf'
                firmware.write_bytes(files['firmware.elf'])
                paths, packages = [], []
                for digest in receipt['packages']:
                    blob = archived[digest + '.msp']
                    package = read_package(blob, allow_archived_abi=True)
                    if package['sha256'] != digest:
                        raise PackageError('Archived package identity mismatch')
                    package_path = path / (digest + '.msp')
                    package_path.write_bytes(blob)
                    paths.append(package_path)
                    packages.append(package)
                images, graph, _ = prepare(paths, firmware, bank, allow_archived_abi=True)
            if graph_digest(images, graph) != activation['good_sha256']:
                return result
            slots = []
            for slot, image in sorted(images.items()):
                package = next(p for p in packages if p['image'] == image)
                offset = bank * 128 * 1024 + 4096 + slot * 16384
                if offset + 16384 > services['size']:
                    return result
                slots.append(dict(slot=slot, name=package['manifest']['name'],
                                  offset=offset, reserved_bytes=16384, image_bytes=len(image)))
            result['services'] = dict(source='confirmed_graph_artifacts', slots=slots)
            return result
        return result
