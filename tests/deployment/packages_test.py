"""Package parser, deterministic admission, and persistent selection boundaries."""
import copy
import io
from pathlib import Path
import struct
import sys
import tempfile
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from micros_tooling.storage.packages import *
from micros_tooling.storage.store import Store
from tools.packaging.demo_packages import build_demo, manifest


def rejected(operation, message=None):
    try:
        operation()
    except PackageError as error:
        if message:
            assert message in str(error), (message, str(error))
    else:
        raise AssertionError('invalid operation was accepted')


build = Path(sys.argv[1])
with tempfile.TemporaryDirectory(prefix='micros-package-test-') as temporary:
    root = Path(temporary)
    enabled = build_demo(build, root / 'packages')
    blobs = [(root / 'packages' / f'{name}.msp').read_bytes() for name in ('publisher', 'fast', 'slow')]
    packages = [read_package(data) for data in blobs]
    plan = admission_plan(packages)
    assert plan == admission_plan(list(reversed(packages)))
    assert plan['resources']['channel_bytes'] == 512 and plan['resources']['handles'] == 4
    for package, blob in zip(packages, blobs):
        assert build_package(package['manifest'], package['image'], package['schemas']) == blob
    publisher = packages[0]
    invalids = []
    changed = copy.deepcopy(publisher['manifest']); changed['console'] = {'format': 1, 'bridge': True, 'views': []}; invalids.append(changed)
    for field, value in [('format', True), ('target', True), ('name', '../escape'), ('persistent_data_version', 1)]:
        changed = copy.deepcopy(publisher['manifest']); changed[field] = value; invalids.append(changed)
    changed = copy.deepcopy(publisher['manifest']); changed['memory']['arena_alignment'] = 3; invalids.append(changed)
    changed = copy.deepcopy(publisher['manifest']); changed['capabilities']['handles'] = 1; invalids.append(changed)
    changed = copy.deepcopy(publisher['manifest']); changed['image_sha256'] = '0' * 64; invalids.append(changed)
    changed = copy.deepcopy(publisher['manifest']); changed['channels'][0]['key'] = 33; invalids.append(changed)
    changed = copy.deepcopy(publisher['manifest']); changed['schemas']['sample'] = '0' * 64; invalids.append(changed)
    changed = copy.deepcopy(publisher['manifest']); changed['abi']['revision'] -= 1; invalids.append(changed)
    for changed in invalids:
        rejected(lambda: build_package(changed, publisher['image'], publisher['schemas']))
    rejected(lambda: read_json(b'{"x":1,"x":2}'), 'duplicate')
    rejected(lambda: read_package(b'X' * (PACKAGE_LIMIT + 1)), 'capacity')
    rejected(lambda: read_package(blobs[0][:-1]))
    for member, compression in [('../outside', zipfile.ZIP_STORED), ('image.mimg', zipfile.ZIP_STORED), ('extra', zipfile.ZIP_DEFLATED)]:
        output = io.BytesIO(blobs[0])
        with zipfile.ZipFile(output, 'a') as archive:
            archive.writestr(member, b'unexpected', compress_type=compression)
        rejected(lambda: read_package(output.getvalue()))
    malformed = copy.deepcopy(packages)
    malformed[1]['manifest']['channels'][0]['major'] += 1
    rejected(lambda: admission_plan(malformed), 'incompatible interface')
    malformed = copy.deepcopy(packages)
    malformed[1]['manifest']['channels'][0]['depth'] = 4
    rejected(lambda: admission_plan(malformed), 'conflicting layout')
    rejected(lambda: admission_plan(packages[1:]), 'no publisher')
    # Schema identity and declared compatibility are independent: a new comment
    # changes the hash, while unchanged declared interface versions remain admissible.
    compatible = copy.deepcopy(packages)
    compatible[0]['schemas']['sample'] += b'// Compatible schema identity fixture.\n'
    compatible[0]['manifest']['schemas']['sample'] = digest(canonical_schema(compatible[0]['schemas']['sample']))
    compatible[0] = read_package(build_package(compatible[0]['manifest'], compatible[0]['image'], compatible[0]['schemas']))
    assert admission_plan(compatible)['channels'] == plan['channels']
    store = Store(root / 'store')
    for blob in blobs:
        store.install(blob)
    assert store.install(blobs[0])['unchanged']
    store.configure(enabled)
    assert Store(store.root).plan() == plan
    old_selection = (store.root / 'enabled.json').read_bytes()
    rejected(lambda: store.configure({'demo.fast': '1.0.0'}), 'no publisher')
    assert (store.root / 'enabled.json').read_bytes() == old_selection
    # Seven installed images coexist while the enabled graph still has three services.
    for version in ('1.0.1', '1.0.2', '1.0.3', '1.0.4'):
        description = copy.deepcopy(publisher['manifest']); description['version'] = version
        store.install(build_package(description, publisher['image'], publisher['schemas']))
    assert sum(map(len, store.index()['services'].values())) == 7
    assert len(store.plan()['services']) == 3
    changed = copy.deepcopy(publisher['manifest']); changed['memory']['arena_bytes'] -= 1
    rejected(lambda: store.install(build_package(changed, publisher['image'], publisher['schemas'])), 'immutable')
    too_many = [copy.deepcopy(publisher) for _ in range(MAX_SERVICES + 1)]
    for index, package in enumerate(too_many): package['manifest']['name'] = f'extra{index}'
    rejected(lambda: admission_plan(too_many), 'loaded services')
    package_path = store.root / 'packages' / f'{publisher["sha256"]}.msp'
    package_path.write_bytes(package_path.read_bytes()[:-1] + b'X')
    rejected(lambda: store.plan(), 'integrity failure')
print('PASS deterministic packages/plans, integrity/parser bounds, interface compatibility, seven installed/three enabled, and unchanged selection after rejection')
