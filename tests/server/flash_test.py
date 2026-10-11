"""Flash layout integrity, enrichment compatibility and unavailable-data semantics."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from server.relay import Registry
from server.artifacts import Artifacts
from server.flash import FlashInventory
from micros_tooling.storage.artifacts import pack, unpack
from micros_tooling.storage.flash_layout import partitions
from micros_tooling.storage.packages import PackageError, digest


def table(entries=None):
    entries = entries or [('nvs', 0x9000, 0x6000), ('services', 0x190000, 0x40000)]
    data = b''.join(struct.pack('<HBBII16sI', 0x50aa, 1, 0x41, offset, size, name.encode(), 0)
                    for name, offset, size in entries)
    return (data + b'\xeb\xeb' + b'\xff' * 14 + hashlib.md5(data).digest()).ljust(0xc00, b'\xff')


class FlashTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.registry = Registry(self.temp.name)
        self.addCleanup(self.registry.db.close)
        self.store = Artifacts(self.registry)
        self.files = {'firmware.elf': b'\x7fELFtest', 'sdkconfig': b'CONFIG_TEST=y\n'}
        self.base = digest(self.files['firmware.elf'])
        self.path = '/v1/artifacts/bases/' + self.base
        self.status = dict(identity=dict(base_sha256=self.base), board=dict(flash_mb=4),
                           activation=dict(good=0, good_sha256='a'*64, pending=False))

    def test_device_layout_survives_management_decoration_without_artifacts(self):
        from micros_tooling.platforms.embedded.telemetry import expand
        for active, rows in ((0xffffffff, []), (0, [[
                'blink', '1.0.0', 4, 0, 1, 0, 32, 2048, 1024,
                1, 1, 0, 0, 1, 1, 0, 0, 0, 0, 0, 512]])):
            status = expand(dict(platform='esp8266', embedded_telemetry=1,
                identity=dict(base_sha256=self.base), active=active,
                good=active, pending=0, base_ota=dict(slot=1),
                service_rows=rows, channel_rows=[], gpio_rows=[]))
            expected = status['flash']
            decorated = self.registry.management.decorate(status)
            self.assertEqual(decorated['flash'], expected)
            self.assertEqual(len(expected['services']['slots']), len(rows))
            images = [p for p in expected['partitions'] if p.get('image')]
            if rows:
                self.assertEqual(images[0]['offset'], 1048576 + 786432 + 4096)
                self.assertEqual(images[0]['image']['image_bytes'], 512)

    def test_historical_native_images_reconstruct_without_deployment_admission(self):
        import io
        import zipfile
        from micros_tooling.platforms.esp32.device import prepare
        from micros_tooling.deployment.deploy import graph_digest
        from micros_tooling.storage.packages import canonical_json
        from micros_tooling.storage.native_image import envelope
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deployment'))
        from terminal_test import package_fixture
        with zipfile.ZipFile(io.BytesIO(package_fixture())) as source:
            manifest = json.loads(source.read('manifest.json'))
        symbols = {f'micros_{kind}_slot{i}': base + i * 0x4000
                   for kind, base in [('code', 0x40100000), ('data', 0x3ffe0000)]
                   for i in range(4)}
        firmware = Path(self.temp.name) / 'firmware.elf'
        firmware.write_bytes(self.files['firmware.elf'])
        self.store.handle('PUT', self.path, pack(dict(self.files, **{'partition-table.bin': table()})))
        for revision in (5, 6):
            with self.subTest(revision=revision):
                descriptor = struct.pack('<12I', 48, 0, revision, 2, 0, 1, 4096, 0, 0, 0, 0, 0)
                image = bytearray(envelope(2, bytes(32), descriptor,
                    code_base=symbols['micros_code_slot2'], data_base=symbols['micros_data_slot2']))
                struct.pack_into('<I', image, 16, revision)
                manifest.update(target=2, abi=dict(major=0, revision=revision), image_sha256=digest(image))
                output = io.BytesIO()
                with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
                    archive.writestr('manifest.json', canonical_json(manifest))
                    archive.writestr('image.mimg', image)
                blob = output.getvalue()
                path = Path(self.temp.name) / 'service.msp'
                path.write_bytes(blob)
                with patch('micros_tooling.storage.packages.ABI_REVISION', 11 - revision), \
                     patch('micros_tooling.platforms.esp32.device.load_symbol_addresses', return_value=symbols), \
                     patch('micros_tooling.config.resources.firmware_gpio_count', return_value=4):
                    with self.assertRaises(PackageError):
                        prepare([path], firmware, 1)
                    images, graph, _ = prepare([path], firmware, 1, allow_archived_abi=True)
                    graph_hash = graph_digest(images, graph)
                    h = digest(blob)
                    key = digest(canonical_json(dict(packages=[h], firmware=self.base)))
                    receipt = dict(id=key, packages=[h], firmware_sha256=self.base, banks={'1': graph_hash})
                    self.store.handle('PUT', '/v1/artifacts/releases/' + key, pack({
                        'receipt.json': canonical_json(receipt), 'configuration.json': b'{}', h + '.msp': blob}))
                    self.status['activation'].update(good=1, good_sha256=graph_hash)
                    slots = FlashInventory(self.registry).describe(self.status)['services']['slots']
                    self.assertEqual(slots, [dict(slot=2, name='test.service',
                        offset=131072 + 4096 + 2 * 16384, reserved_bytes=16384, image_bytes=len(image))])

    def test_partition_checksum_overlap_and_bounds(self):
        self.assertEqual(partitions(table())[1]['size'], 262144)
        damaged = bytearray(table()); damaged[20] ^= 1
        with self.assertRaises(PackageError): partitions(bytes(damaged))
        with self.assertRaises(PackageError): partitions(table([('a',0x9000,0x6000),('b',0xa000,0x1000)]))
        with self.assertRaises(PackageError): partitions(b'\xff'*3072)
        with self.assertRaises(PackageError): partitions(table([('a',0xfff000,0x2000)]))

    def test_enrich_old_base_without_replacing_or_dropping_table(self):
        self.store.handle('PUT', self.path, pack(self.files))
        enriched = dict(self.files, **{'partition-table.bin':table()})
        self.store.handle('PUT', self.path, pack(enriched))
        self.store.handle('PUT', self.path, pack(self.files))
        self.assertEqual(unpack(self.store.handle('GET',self.path,b'')[1]), enriched)
        changed = dict(enriched, **{'partition-table.bin':table([('other',0x9000,0x1000)])})
        with self.assertRaises(PackageError): self.store.handle('PUT',self.path,pack(changed))

    def test_missing_artifacts_and_cache_refresh_after_enrichment(self):
        inventory=FlashInventory(self.registry)
        self.assertEqual(inventory.describe(self.status)['partitions'], [])
        self.store.handle('PUT',self.path,pack(dict(self.files,**{'partition-table.bin':table()})))
        result=inventory.describe(self.status)
        self.assertEqual(result['source'],'base_build_artifact')
        self.assertEqual(len(result['partitions']),2)
        self.assertNotIn('services',result)  # No image guesses from service count or RAM.
        self.assertNotIn('sdkconfig',json.dumps(result))

    def test_trial_keeps_layout_but_never_attributes_previous_images(self):
        self.store.handle('PUT',self.path,pack(dict(self.files,**{'partition-table.bin':table()})))
        self.status['activation']['pending']=True
        with patch('micros_tooling.platforms.esp32.device.prepare') as prepare:
            result=FlashInventory(self.registry).describe(self.status)
            prepare.assert_not_called()
        self.assertEqual(len(result['partitions']),2)
        self.assertNotIn('services',result)

    def test_wrong_base_or_chip_size_does_not_reuse_layout(self):
        self.store.handle('PUT',self.path,pack(dict(self.files,**{'partition-table.bin':table()})))
        inventory=FlashInventory(self.registry)
        self.assertEqual(len(inventory.describe(self.status)['partitions']),2)
        self.status['identity']['base_sha256']='b'*64
        self.assertEqual(inventory.describe(self.status)['partitions'],[])
        self.status['identity']['base_sha256']=self.base
        self.status['board']['flash_mb']=1
        self.assertEqual(inventory.describe(self.status)['partitions'],[])

    def test_reconstructed_graph_required_and_slot_order_comes_from_image(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deployment'))
        from terminal_test import package_fixture
        from micros_tooling.storage.packages import read_package, canonical_json
        package=package_fixture()
        h=digest(package)
        key=digest(canonical_json(dict(packages=[h],firmware=self.base)))
        receipt=dict(id=key,packages=[h],firmware_sha256=self.base,banks={'0':'a'*64})
        self.store.handle('PUT',self.path,pack(dict(self.files,**{'partition-table.bin':table()})))
        files={'receipt.json':json.dumps(receipt).encode(),'configuration.json':b'{}',h+'.msp':package}
        self.store.handle('PUT','/v1/artifacts/releases/'+key,pack(files))
        image=read_package(package)['image']
        with patch('micros_tooling.platforms.esp32.device.prepare',return_value=({2:image},b'graph',{})), \
             patch('micros_tooling.deployment.deploy.graph_digest',return_value='b'*64):
            self.assertNotIn('services',FlashInventory(self.registry).describe(self.status))
        with patch('micros_tooling.platforms.esp32.device.prepare',return_value=({2:image},b'graph',{})), \
             patch('micros_tooling.deployment.deploy.graph_digest',return_value='a'*64):
            slots=FlashInventory(self.registry).describe(self.status)['services']['slots']
        self.assertEqual(len(slots),1)
        self.assertEqual(slots[0]['slot'],2)
        self.assertEqual(slots[0]['offset'],4096+2*16384)
        self.assertEqual(slots[0]['image_bytes'],len(image))

if __name__=='__main__': unittest.main()
