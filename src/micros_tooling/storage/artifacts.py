"""Bounded, hash-verified artifact envelopes shared by operators and the server."""
import base64
import json
import re
from pathlib import Path
from micros_tooling.storage.packages import digest, require, canonical_json, read_package

LIMIT = 32 * 1024 * 1024


def pack(files):
    return json.dumps({name: dict(sha256=digest(data), data=base64.b64encode(data).decode())
                       for name, data in files.items()}, sort_keys=True, separators=(',', ':')).encode()


def unpack(body):
    require(len(body) <= LIMIT, 'Artifact bundle exceeds 32 MiB')
    value = json.loads(body)
    require(isinstance(value, dict) and 1 <= len(value) <= 10, 'Invalid artifact file count')
    files = {}
    for name, entry in value.items():
        require(isinstance(name, str) and re.fullmatch(r'[a-zA-Z0-9_.-]+', name)
                and name not in ('.', '..'), 'Invalid artifact filename')
        require(isinstance(entry, dict) and entry.keys() == {'sha256', 'data'}, 'Invalid artifact entry')
        data = base64.b64decode(entry['data'], validate=True)
        require(digest(data) == entry['sha256'], 'Artifact checksum mismatch')
        files[name] = data
    return files


def validate_base(key, files):
    require({'firmware.elf', 'sdkconfig'} <= files.keys() <=
            {'firmware.elf', 'sdkconfig', 'partition-table.bin'}, 'Base requires ELF, sdkconfig and optional partition table')
    require(files['firmware.elf'].startswith(b'\x7fELF') and digest(files['firmware.elf']) == key,
            'Base ELF identity mismatch')
    require(0 < len(files['sdkconfig']) <= 1024 * 1024, 'Missing or oversized sdkconfig')
    if 'partition-table.bin' in files:
        from micros_tooling.storage.flash_layout import partitions
        partitions(files['partition-table.bin'])


def validate_release(key, files):
    receipt = json.loads(files['receipt.json'])
    hashes = receipt['packages']
    require(isinstance(hashes, list) and 1 <= len(hashes) <= 4
            and all(isinstance(h, str) and re.fullmatch('[0-9a-f]{64}', h) for h in hashes),
            'Invalid release packages')
    require(files.keys() == {'receipt.json', 'configuration.json', *[h + '.msp' for h in hashes]},
            'Unexpected release files')
    identity = digest(canonical_json(dict(packages=hashes, firmware=receipt['firmware_sha256'])))
    require(identity == key == receipt['id'], 'Release identity mismatch')
    for h in hashes:
        require(digest(files[h + '.msp']) == h, 'Release package mismatch')
        read_package(files[h + '.msp'], allow_archived_abi=True)
    json.loads(files['configuration.json'])
    return receipt


def publish_base(remote, firmware):
    firmware = Path(firmware)
    files = {'firmware.elf': firmware.read_bytes(), 'sdkconfig': firmware.with_name('sdkconfig').read_bytes()}
    table = firmware.parent / 'partition_table' / 'partition-table.bin'
    if not table.exists():
        table = firmware.with_name('partition-table.bin')
    if table.exists():
        files['partition-table.bin'] = table.read_bytes()
    key = digest(files['firmware.elf'])
    validate_base(key, files)
    remote.raw('PUT', '/v1/artifacts/bases/' + key, pack(files))
    return key


def fetch_base(remote, workspace, status):
    from micros_tooling.storage.store import atomic_write
    key = status.get('identity', {}).get('base_sha256', '')
    require(isinstance(key, str) and re.fullmatch('[0-9a-f]{64}', key), 'Device returned invalid base identity')
    directory = workspace.root / 'artifacts' / 'bases' / key
    envelope = directory / 'bundle.json'
    files = None
    if envelope.exists():
        try:
            files = unpack(envelope.read_bytes())
            validate_base(key, files)
        except (ValueError, KeyError, TypeError):
            files = None
    if files is None:
        from micros_tooling.communication.remote import RemoteRejected
        try:
            body = remote.raw('GET', '/v1/artifacts/bases/' + key)
        except RemoteRejected as error:
            if error.status == 404:
                raise ValueError(f'Server has no base artifacts for {key}. Publish the original build with '
                                 './micros server publish-base --firmware PATH/firmware.elf') from error
            raise
        files = unpack(body)
        validate_base(key, files)
        atomic_write(envelope, body)
    # Rewrite from the verified envelope so damaged extracted cache files cannot be used.
    for name, data in files.items():
        atomic_write(directory / name, data)
    return directory / 'firmware.elf'


def archive_release(remote, receipt, packages, configuration):
    files = {'receipt.json': canonical_json(receipt), 'configuration.json': canonical_json(configuration),
             **{Path(p).name: Path(p).read_bytes() for p in packages}}
    validate_release(receipt['id'], files)
    remote.raw('PUT', f'/v1/artifacts/releases/{receipt["id"]}', pack(files))
    remote.raw('POST', f'/v1/artifacts/devices/{remote.device_id}/{receipt["id"]}', b'{}')


def confirm_release(remote, receipt, status):
    remote.raw('POST', f'/v1/artifacts/devices/{remote.device_id}/{receipt["id"]}',
               canonical_json(dict(status=status)))


def sync_releases(remote, workspace, name):
    from micros_tooling.storage.store import atomic_write
    entries = json.loads(remote.raw('GET', f'/v1/artifacts/devices/{remote.device_id}'))
    for entry in entries:
        key = entry['release']
        require(isinstance(key, str) and re.fullmatch('[0-9a-f]{64}', key), 'Invalid server release identity')
        files = unpack(remote.raw('GET', '/v1/artifacts/releases/' + key))
        receipt = validate_release(key, files)
        for filename, data in files.items():
            atomic_write(workspace.root / 'snapshots' / key / filename, data)
        configurations = json.loads(remote.raw('GET', f'/v1/artifacts/releases/{key}/configurations'))
        for record in configurations:
            data = canonical_json(record['configuration'])
            require(digest(data) == record['sha256'], 'Configuration checksum mismatch')
            atomic_write(workspace.root / 'snapshots' / key / 'configurations' / (record['sha256'] + '.json'), data)
    previous = workspace.history(name)
    confirmed = {e['release']: e['confirmed'] for e in entries if e['confirmed']}
    history = [dict(snapshot=key, confirmed_at=at) for key, at in confirmed.items()]
    history.sort(key=lambda e: e['confirmed_at'])
    if any(event['snapshot'] not in confirmed for event in previous):
        # Preserve legacy or interrupted-client evidence without treating it as server history.
        workspace.write(Path('devices') / name / 'history-archive' / (digest(canonical_json(previous)) + '.json'), previous)
    workspace.write(Path('devices') / name / 'history.json', history)
