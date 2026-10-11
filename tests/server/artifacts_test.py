"""Artifact persistence, authentication, corruption rejection and empty-client recovery."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from server.relay import Registry, Server
from micros_tooling.storage.artifacts import pack, unpack, fetch_base, publish_base, archive_release, sync_releases, confirm_release
from micros_tooling.storage.packages import digest, PackageError, canonical_json
from micros_tooling.storage.workspace import Workspace

DEVICE = '0123456789ab'
ADMIN = 'a' * 64


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = Registry(self.root / 'server')
        self.addCleanup(self.registry.db.close)
        self.registry.enroll(DEVICE, 'test', 'b' * 64)
        self.server = Server(('127.0.0.1', 0), self.registry, ADMIN)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.files = {'firmware.elf': b'\x7fELFtest-base', 'sdkconfig': b'CONFIG_TEST=y\n'}
        self.key = digest(self.files['firmware.elf'])

    def request(self, method, path, body=b'', token=ADMIN):
        client = http.client.HTTPConnection(*self.server.server_address)
        client.request(method, path, body, {'Authorization': 'Bearer ' + token})
        response = client.getresponse()
        result = response.status, response.read()
        client.close()
        return result

    def test_operator_only_and_immutable_roundtrip(self):
        path = '/v1/artifacts/bases/' + self.key
        body = pack(self.files)
        self.assertEqual(self.request('PUT', path, body, 'b' * 64)[0], 401)
        self.assertEqual(self.request('PUT', path, body)[0], 200)
        self.assertEqual(self.request('PUT', path, body)[0], 200)
        self.assertEqual(unpack(self.request('GET', path)[1]), self.files)
        from server.remote import RegistryRemote
        self.assertEqual(unpack(RegistryRemote(self.registry, DEVICE).raw('GET', path)), self.files)
        self.assertEqual(self.request('GET', path, token='b' * 64)[0], 401)
        changed = dict(self.files, sdkconfig=b'different')
        self.assertEqual(self.request('PUT', path, pack(changed))[0], 400)
        self.assertEqual(unpack(self.request('GET', path)[1]), self.files)

    def test_corruption_and_wrong_key_leave_no_object(self):
        path = '/v1/artifacts/bases/' + self.key
        body = json.loads(pack(self.files))
        body['sdkconfig']['sha256'] = '0' * 64
        self.assertEqual(self.request('PUT', path, json.dumps(body).encode())[0], 400)
        self.assertEqual(self.request('GET', path)[0], 404)
        self.assertEqual(self.request('PUT', '/v1/artifacts/bases/' + '0' * 64, pack(self.files))[0], 400)
        self.assertEqual(self.request('PUT', path, pack(dict(self.files, token=b'secret')))[0], 400)

    def test_large_elf_persists_across_store_reopen(self):
        files = dict(self.files, **{'firmware.elf': b'\x7fELF' + b'x' * 100000})
        key = digest(files['firmware.elf'])
        self.assertEqual(self.request('PUT', '/v1/artifacts/bases/' + key, pack(files))[0], 200)
        from server.artifacts import Artifacts
        reopened = Registry(self.root / 'server')
        try:
            self.assertEqual(unpack(Artifacts(reopened).handle('GET', '/v1/artifacts/bases/' + key, b'')[1]), files)
        finally:
            reopened.db.close()

    def test_empty_client_fetch_and_damaged_cache_recovery(self):
        self.request('PUT', '/v1/artifacts/bases/' + self.key, pack(self.files))
        outer = self
        class Remote:
            calls = 0
            def raw(self, method, path, body=b''):
                self.calls += 1
                code, data = outer.request(method, path, body)
                self.assert_code = code
                return data
        remote = Remote()
        workspace = Workspace(self.root / 'client')
        status = {'identity': {'base_sha256': self.key}}
        firmware = fetch_base(remote, workspace, status)
        self.assertEqual(firmware.read_bytes(), self.files['firmware.elf'])
        firmware.write_bytes(b'damaged extraction')
        self.assertEqual(fetch_base(remote, workspace, status).read_bytes(), self.files['firmware.elf'])
        self.assertEqual(remote.calls, 1)
        firmware.with_name('bundle.json').write_bytes(b'{}')
        fetch_base(remote, workspace, status)
        self.assertEqual(remote.calls, 2)

    def test_release_archive_recovers_packages_config_and_rollback_history(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deployment'))
        from terminal_test import package_fixture
        outer = self
        class Remote:
            device_id = DEVICE
            def raw(self, method, path, body=b''):
                code, data = outer.request(method, path, body)
                if code != 200:
                    raise ValueError(f'HTTP {code}')
                return data
        remote = Remote()
        firmware = self.root / 'firmware.elf'
        firmware.write_bytes(self.files['firmware.elf'])
        firmware.with_name('sdkconfig').write_bytes(self.files['sdkconfig'])
        publish_base(remote, firmware)
        author = Workspace(self.root / 'author')
        receipts = []
        for i in range(2):
            package = self.root / 'service.msp'
            package.write_bytes(package_fixture(version=f'1.0.{i}'))
            graph = str(i + 1) * 64
            receipt = author.snapshot([package], {'banks': {0: {'digest': graph}, 1: {'digest': graph}}}, firmware)
            packages = author.snapshot_packages(receipt, firmware)
            archive_release(remote, receipt, packages, {'unit_toml': 'example', 'resolved': {'services': [i]}})
            # Merely archived bytes are not claimed as a successful deployment.
            entries = json.loads(remote.raw('GET', f'/v1/artifacts/devices/{DEVICE}'))
            self.assertIsNone(next(e for e in entries if e['release'] == receipt['id'])['confirmed'])
            status = dict(identity=dict(device_id=DEVICE, base_sha256=self.key),
                          activation=dict(good=0, good_sha256=graph, pending=0),
                          services=[dict(state='Running', result=0)])
            confirm_release(remote, receipt, status)
            receipts.append(receipt)
        archive_release(remote, receipt, packages, {'unit_toml': 'same executable, different authored comment'})
        variants = json.loads(remote.raw('GET', f'/v1/artifacts/releases/{receipt["id"]}/configurations'))
        self.assertEqual(len(variants), 2)
        client = Workspace(self.root / 'fresh')
        client.write('devices/unit/history.json', [dict(snapshot='f' * 64, confirmed_at='2000-01-01T00:00:00+00:00')])
        sync_releases(remote, client, 'unit')
        sync_releases(remote, client, 'unit')
        self.assertEqual(len(client.history('unit')), 2)
        self.assertEqual(client.rollback_target('unit', status)['id'], receipts[0]['id'])
        self.assertEqual(len(client.snapshot_packages(receipts[0], firmware)), 1)
        self.assertEqual(json.loads((client.root / 'snapshots' / receipts[0]['id'] / 'configuration.json').read_text())['unit_toml'], 'example')
        status['identity']['device_id'] = 'f' * 12
        with self.assertRaises(ValueError):
            confirm_release(remote, receipt, status)

    def test_archived_abi_is_not_deployment_admission(self):
        import io
        import struct
        import zipfile
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deployment'))
        from terminal_test import package_fixture
        from micros_tooling.storage.packages import read_package
        from micros_tooling.storage.artifacts import validate_release
        with zipfile.ZipFile(io.BytesIO(package_fixture())) as source:
            files = {name: source.read(name) for name in source.namelist()}
        manifest = json.loads(files['manifest.json'])
        image = bytearray(files['image.mimg'])
        struct.pack_into('<I', image, 16, 5)
        manifest['abi']['revision'] = 5
        manifest['image_sha256'] = digest(image)
        files['image.mimg'] = bytes(image)
        files['manifest.json'] = canonical_json(manifest)
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as target:
            for name, data in files.items():
                target.writestr(name, data)
        legacy = output.getvalue()
        self.assertEqual(read_package(legacy, allow_archived_abi=True)['manifest']['abi']['revision'], 5)
        with self.assertRaises(PackageError):
            read_package(legacy)
        package_hash = digest(legacy)
        key = digest(canonical_json(dict(packages=[package_hash], firmware=self.key)))
        receipt = dict(id=key, packages=[package_hash], firmware_sha256=self.key)
        archive = {'receipt.json': canonical_json(receipt), 'configuration.json': b'{}',
                   package_hash + '.msp': legacy}
        self.assertEqual(validate_release(key, archive), receipt)

    def test_path_traversal_rejected(self):
        with self.assertRaises(PackageError):
            unpack(pack({'../token': b'test'}))


if __name__ == '__main__':
    unittest.main()
