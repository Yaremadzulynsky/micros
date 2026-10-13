"""Version-1 service packages, validated manifests, and deterministic graph admission."""
from __future__ import annotations

import hashlib
import os
import io
import json
from pathlib import Path
import re
import struct
import zipfile
import zlib
from micros_tooling.storage.native_image import ABI_MAJOR, ABI_REVISION, HEADER_BYTES, IMAGE_MAGIC, FORMAT_VERSION, NATIVE_HOST_TARGET

# Host development bounds: one M1 image plus small manifest/schema records fits
# within 5 MiB. Fixed entry/count limits prevent archive metadata or expansion abuse.
IMAGE_LIMIT = 4 * 1024 * 1024
PACKAGE_LIMIT = 5 * 1024 * 1024
MANIFEST_LIMIT = 64 * 1024
SCHEMA_LIMIT = 64 * 1024
MAX_SCHEMAS = 4
MAX_SERVICES = 4
MAX_HANDLES = 8
MAX_CHANNELS = 4
MAX_CHANNEL_DEPTH = 8
MAX_PAYLOAD = 256
CHANNEL_POOL_BYTES = MAX_CHANNELS * MAX_CHANNEL_DEPTH * MAX_PAYLOAD
# Match the host BSP: libc needs 64 KiB; Linux ARM64 vector-state support may require more.
HOST_STACK_FLOOR = max(64 * 1024, os.sysconf("SC_THREAD_STACK_MIN"))
IDENTIFIER = re.compile(r'[a-z][a-z0-9_.-]{0,63}\Z')
VERSION = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z')
DIGEST = re.compile(r'[0-9a-f]{64}\Z')


class PackageError(ValueError):
    """An actionable package, compatibility, or resource-admission failure."""


def require(condition, message):
    if not condition:
        raise PackageError(message)


def bounded_read(path, limit):
    with Path(path).open('rb') as stream:
        data = stream.read(limit + 1)
    require(len(data) <= limit, f'{path}: exceeds {limit}-byte limit')
    return data


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode() + b'\n'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical_schema(data):
    """Canonical identity: UTF-8, LF endings, stripped line tails, one final newline."""
    return ('\n'.join(line.rstrip() for line in data.decode('utf-8').splitlines()) + '\n').encode()


def integer(value, low, high, field):
    require(type(value) is int and low <= value <= high, f'{field}: expected integer {low}..{high}')
    return value


def identifier(value, field):
    require(isinstance(value, str) and IDENTIFIER.fullmatch(value), f'{field}: invalid identifier')
    return value


def object_keys(value, required, field):
    require(isinstance(value, dict) and set(value) == set(required), f'{field}: expected fields {sorted(required)}')


def read_json(data):
    def unique_pairs(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, f'duplicate JSON key: {key}')
            value[key] = item
        return value
    try:
        return json.loads(data, object_pairs_hook=unique_pairs)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise PackageError(f'invalid JSON: {error}') from error


def image_metadata(image, *, abi_revision=ABI_REVISION):
    require(HEADER_BYTES <= len(image) <= IMAGE_LIMIT, 'image: invalid envelope length')
    words = struct.unpack('<16I', image[:HEADER_BYTES])
    magic, version, target, major, revision, code_base, data_base, code_bytes, data_bytes, bss_bytes, descriptor, checksum, *reserved = words
    require(magic == IMAGE_MAGIC and (version == FORMAT_VERSION or (version == 2 and target == 2)), 'image: unsupported format')
    require((major, revision) == (ABI_MAJOR, abi_revision), 'image: ABI mismatch')
    require(target in (1, 2, 3, 4, 5, 6), 'image: unsupported target')
    require(not any(reserved[2:] if version == 2 else reserved), 'image: reserved fields must be zero')
    if version == 2:
        require(reserved[0] and not (reserved[0] | reserved[1]) % 4 and reserved[1] < code_bytes
                and reserved[0] + code_bytes <= 0xffffffff, 'image: invalid flash layout')
    require(code_bytes and HEADER_BYTES + code_bytes + data_bytes == len(image), 'image: section lengths do not match file')
    require(zlib.crc32(image[HEADER_BYTES:]) == checksum, 'image: checksum mismatch')
    if target not in (2, 5, 6):
        require(not any((code_base, data_base, data_bytes, bss_bytes, descriptor)), 'image: invalid host layout')
    else:
        require(not (code_base | data_base | code_bytes | data_bytes | bss_bytes | descriptor) % 4, 'image: unaligned ESP32 sections')
        require(data_bytes >= 48 and descriptor <= data_bytes - 48, 'image: descriptor outside initialized data')
    return dict(target=target, code_bytes=code_bytes, data_bytes=data_bytes, bss_bytes=bss_bytes,
                code_base=code_base, data_base=data_base, descriptor_offset=descriptor,
                rodata_base=reserved[0] if version == 2 else 0,
                rodata_bytes=reserved[1] if version == 2 else 0)


def validate_manifest(manifest, image, schemas, *, allow_archived_abi=False):
    object_keys({key: value for key, value in manifest.items() if key not in ('config', 'build_identity', 'board_bindings', 'published_ports', 'ipc_bridge', 'commands')}, ('format', 'name', 'version', 'target', 'abi', 'image_sha256', 'memory',
                           'capabilities', 'channels', 'schemas', 'persistent_data_version'), 'manifest')
    if 'build_identity' in manifest:
        build = manifest['build_identity']
        object_keys(build, ('source_sha256', 'slot'), 'build identity')
        require(isinstance(build['source_sha256'], str) and DIGEST.fullmatch(build['source_sha256']),
                'build identity: invalid source SHA-256')
        integer(build['slot'], 0, 3, 'build slot')
    if 'board_bindings' in manifest:
        from micros_tooling.config.resources import validate_bindings
        validate_bindings(manifest['board_bindings'], target=manifest.get('target', 2))
    configuration = manifest.get('config', '')
    require(isinstance(configuration, str) and len(configuration) <= 512 and
            len(configuration) % 2 == 0 and all(c in '0123456789abcdef' for c in configuration),
            'config: expected at most 256 bytes of lowercase hex')
    integer(manifest['format'], 1, 1, 'manifest format')
    identifier(manifest['name'], 'name')
    require(isinstance(manifest['version'], str) and VERSION.fullmatch(manifest['version']), 'version: expected numeric major.minor.patch')
    object_keys(manifest['abi'], ('major', 'revision'), 'abi')
    integer(manifest['abi']['major'], ABI_MAJOR, ABI_MAJOR, 'ABI major')
    revision = manifest['abi']['revision']
    if allow_archived_abi:
        require(type(revision) is int and revision in (5, 6, 7), 'Unsupported archived ABI revision')
    else:
        integer(revision, ABI_REVISION, ABI_REVISION, 'ABI revision')
    integer(manifest['target'], 1, 6, 'target')
    metadata = image_metadata(image, abi_revision=revision)
    require(manifest['target'] == metadata['target'], 'manifest/image target mismatch')
    require(manifest['image_sha256'] == digest(image), 'image: SHA-256 mismatch')
    integer(manifest['persistent_data_version'], 0, 0, 'persistent_data_version')  # v1 has no service data migrations.
    memory = manifest['memory']
    object_keys({k:v for k,v in memory.items() if k != 'arena'}, ('arena_bytes', 'arena_alignment', 'stack_bytes'), 'memory')
    require(memory.get('arena', 'RAM') in ('RAM', 'PSRAM'), 'Invalid arena placement')
    integer(memory['arena_bytes'], 0, 4096, 'arena_bytes')
    alignment = integer(memory['arena_alignment'], 1, 16, 'arena_alignment')
    require(not alignment & (alignment - 1), 'arena_alignment: expected power of two')
    integer(memory['stack_bytes'], 1, 16384, 'stack_bytes')
    capabilities = manifest['capabilities']
    object_keys(capabilities, ('handles', 'timers', 'gpio'), 'capabilities')
    integer(capabilities['handles'], 0, MAX_HANDLES, 'handles')
    integer(capabilities['timers'], 0, MAX_HANDLES, 'timers')
    require(isinstance(capabilities['gpio'], list) and len(capabilities['gpio']) <= 4, 'gpio: at most four lines')
    for line in capabilities['gpio']:
        integer(line, 0, 3, 'gpio line')
    require(len(set(capabilities['gpio'])) == len(capabilities['gpio']), 'gpio: duplicate line')
    require(isinstance(manifest['schemas'], dict) and len(manifest['schemas']) <= MAX_SCHEMAS, 'schemas: invalid table')
    require(set(manifest['schemas']) == set(schemas), 'schemas: manifest/archive entries differ')
    for name, expected_hash in manifest['schemas'].items():
        identifier(name, 'schema name')
        require(isinstance(expected_hash, str) and DIGEST.fullmatch(expected_hash), 'schema: invalid SHA-256')
        require(len(schemas[name]) <= SCHEMA_LIMIT and digest(canonical_schema(schemas[name])) == expected_hash, f'schema {name}: SHA-256 mismatch')
    channels = manifest['channels']
    require(isinstance(channels, list) and len(channels) <= MAX_HANDLES, 'channels: too many declarations')
    seen = set()
    for channel in channels:
        object_keys({k:v for k,v in channel.items() if k!='coordination'}, ('name', 'key', 'access', 'policy', 'depth', 'max_payload', 'schema',
                              'interface', 'major', 'minor', 'accepts_minor'), 'channel')
        if 'coordination' in channel:
            require(channel['coordination'] in ('state','action','event') and revision>=7 and channel['policy']=='latest' and channel['depth']==1 and channel['max_payload']<=64, 'Invalid coordination channel')
        identifier(channel['name'], 'channel name')
        integer(channel['key'], 1, 32, 'channel key')  # One bit per key in the admitted capability mask.
        require(channel['access'] in ('publish', 'subscribe'), 'channel: invalid access')
        require(channel['policy'] in ('stream', 'latest'), 'channel: invalid policy')
        integer(channel['depth'], 1, MAX_CHANNEL_DEPTH, 'channel depth')
        require(channel['policy'] != 'latest' or channel['depth'] == 1, 'latest channel depth must be one')
        integer(channel['max_payload'], 1, MAX_PAYLOAD, 'channel max_payload')
        require(channel['schema'] in schemas, 'channel: unknown schema')
        identifier(channel['interface'], 'interface name')
        integer(channel['major'], 0, 65535, 'interface major')
        integer(channel['minor'], 0, 65535, 'interface minor')
        accepted = channel['accepts_minor']
        require(isinstance(accepted, list) and len(accepted) == 2, 'accepts_minor: expected inclusive [min,max]')
        integer(accepted[0], 0, 65535, 'minimum minor'); integer(accepted[1], accepted[0], 65535, 'maximum minor')
        endpoint = channel['key'], channel['access']
        require(endpoint not in seen, 'duplicate channel endpoint')
        seen.add(endpoint)
    if 'commands' in manifest:
        from micros_tooling.commands.metadata import validate as validate_commands
        validate_commands(manifest['commands'], channels, schemas)
    if 'ipc_bridge' in manifest:
        require(type(manifest['ipc_bridge']) is bool, 'Invalid IPC bridge marker')
    if 'published_ports' in manifest:
        from micros_tooling.communication.channel_metadata import validate
        validate(manifest['published_ports'], channels)
    minimum_handles = capabilities['timers'] + len(capabilities['gpio']) + len(channels)
    require(minimum_handles <= capabilities['handles'], f'handles: declaration needs {minimum_handles}, budget is {capabilities["handles"]}')
    # MCU descriptors can be checked without executing a query function.
    if metadata['target'] in (2, 5, 6):
        offset = HEADER_BYTES + metadata['code_bytes'] + metadata['descriptor_offset']
        descriptor = struct.unpack_from('<8I', image, offset)
        require(descriptor[:4] == (48, ABI_MAJOR, revision, metadata['target']), 'MCU descriptor compatibility')
        require(descriptor[7] == int(memory.get('arena', 'RAM') == 'PSRAM'), 'manifest/native arena placement mismatch')
        require(descriptor[4:7] == (memory['arena_bytes'], memory['arena_alignment'], memory['stack_bytes']), 'manifest/native descriptor memory mismatch')
    return metadata


def build_package(manifest, image, schemas):
    validate_manifest(manifest, image, schemas)
    records = {'manifest.json': canonical_json(manifest), 'image.mimg': image}
    records.update({f'schemas/{name}.proto': data for name, data in schemas.items()})
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(records.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))  # ZIP's earliest timestamp makes output deterministic.
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    package = output.getvalue()
    require(len(package) <= PACKAGE_LIMIT, 'package: capacity exceeded')
    return package


def read_package(package, *, allow_archived_abi=False):
    """Read a package; archive mode inspects ABI 5/6 history without admitting it."""
    require(len(package) <= PACKAGE_LIMIT, 'package: capacity exceeded')
    try:
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            require(2 <= len(entries) <= 2 + MAX_SCHEMAS and len(set(names)) == len(names), 'archive: invalid/duplicate entry count')
            require('manifest.json' in names and 'image.mimg' in names, 'archive: required files missing')
            for entry in entries:
                require(entry.compress_type == zipfile.ZIP_STORED and not entry.flag_bits & 1, 'archive: compression/encryption unsupported')
                limit = IMAGE_LIMIT if entry.filename == 'image.mimg' else MANIFEST_LIMIT if entry.filename == 'manifest.json' else SCHEMA_LIMIT
                require(entry.file_size <= limit and entry.compress_size == entry.file_size, 'archive: invalid entry length')
            manifest = read_json(archive.read('manifest.json'))
            require(isinstance(manifest, dict) and isinstance(manifest.get('schemas'), dict), 'manifest: missing schema table')
            expected = {'manifest.json', 'image.mimg'} | {f'schemas/{name}.proto' for name in manifest['schemas']}
            require(set(names) == expected, 'archive: unexpected path/member')
            schemas = {name: archive.read(f'schemas/{name}.proto') for name in manifest['schemas']}
            image = archive.read('image.mimg')
            metadata = validate_manifest(manifest, image, schemas, allow_archived_abi=allow_archived_abi)
            return {'manifest': manifest, 'image': image, 'schemas': schemas, 'metadata': metadata, 'sha256': digest(package)}
    except (zipfile.BadZipFile, KeyError, UnicodeError, struct.error, TypeError) as error:
        raise PackageError(f'invalid package: {error}') from error


def admission_plan(packages, target=NATIVE_HOST_TARGET):
    """Pure, deterministic planning; neither executes code nor mutates installed selections."""
    require(len(packages) <= MAX_SERVICES, f'loaded services: need {len(packages)}, limit {MAX_SERVICES}')
    totals = dict(image_bytes=0, arena_bytes=0, requested_stack_bytes=0, host_stack_bytes=0, handles=0, channel_bytes=0)
    services, channel_table, gpio_owners = [], {}, {}
    names = set()
    for package in sorted(packages, key=lambda item: item['manifest']['name']):
        manifest, metadata = package['manifest'], package['metadata']
        name = manifest['name']
        require(name not in names, f'duplicate service {name}'); names.add(name)
        require(manifest['target'] == target, f'{name}: target mismatch')
        memory, capabilities = manifest['memory'], manifest['capabilities']
        if target == 2:
            # Feather V2 reserves four independent 8 KiB IRAM / 4 KiB DRAM slots.
            require(metadata['code_bytes'] <= 12288 and metadata['data_bytes'] + metadata['bss_bytes'] <= 4096,
                    f'{name}: ESP32 code/data slot capacity')
            # Physical-base GPIO capacity is checked against its ELF in prepare().
        if target == 6:
            require(64 + metadata['code_bytes'] + metadata['data_bytes'] <= 0x7c00 and metadata['data_bytes'] + metadata['bss_bytes'] <= 1024, f'{name}: ESP8266 code/data slot capacity')
            require(memory.get('arena', 'RAM') == 'RAM' and 512 <= memory['stack_bytes'] <= 4096, f'{name}: ESP8266 memory/stack budget')
        if target == 5:
            require(64 + metadata['code_bytes'] + metadata['data_bytes'] <= 0x3c00 and metadata['data_bytes'] + metadata['bss_bytes'] <= 512, f'{name}: ARM code/data slot capacity')
            require(memory.get('arena', 'RAM') == 'RAM' and 512 <= memory['stack_bytes'] <= 4096, f'{name}: ARM memory placement/stack budget')
        totals['image_bytes'] += metadata['code_bytes'] + metadata['data_bytes']
        totals['arena_bytes'] += memory['arena_bytes']
        totals['requested_stack_bytes'] += memory['stack_bytes']
        totals['host_stack_bytes'] += max(HOST_STACK_FLOOR, memory['stack_bytes']) if target not in (2, 5, 6) else memory['stack_bytes']
        totals['handles'] += capabilities['handles']
        for line in capabilities['gpio']:
            require(line not in gpio_owners, f'GPIO {line}: exclusive conflict between {gpio_owners.get(line)} and {name}')
            gpio_owners[line] = name
        permissions = dict(timers=capabilities['timers'], gpio_mask=sum(1 << line for line in capabilities['gpio']), publish_mask=0, subscribe_mask=0)
        for declaration in manifest['channels']:
            permissions[declaration['access'] + '_mask'] |= 1 << (declaration['key'] - 1)
            key = declaration['key']
            layout = {field: declaration[field] for field in ('name', 'key', 'policy', 'depth', 'max_payload')}
            entry = channel_table.setdefault(key, {'layout': layout, 'kind': declaration.get('coordination'), 'publish': [], 'subscribe': []})
            require(entry['kind']==declaration.get('coordination'), f'channel {key}: conflicting coordination kinds')
            require(entry['layout'] == layout, f'channel {key}: conflicting layout/name')
            entry[declaration['access']].append((name, declaration))
        services.append({'name': name, 'version': manifest['version'], 'package_sha256': package['sha256'],
                         'memory': memory, 'handles': capabilities['handles'], 'permissions': permissions, 'config': manifest.get('config', '')})
    require(len(channel_table) <= MAX_CHANNELS, f'channels: limit {MAX_CHANNELS}')
    channel_names = [entry['layout']['name'] for entry in channel_table.values()]
    require(len(set(channel_names)) == len(channel_names), 'channel name mapped to multiple keys')
    for entry in channel_table.values():
        layout = entry['layout']
        require(entry['publish'] or entry['kind'], f'{layout["name"]}: no publisher in enabled graph')
        if entry['kind']:
            require(len(entry['publish'])<=1, 'Coordination requires one publisher')
            require(entry['kind']!='action' or len(entry['subscribe'])<=1, 'Action requires one executor')
        for consumer_name, consumer in entry['subscribe']:
            for producer_name, producer in entry['publish']:
                require((producer['interface'], producer['major']) == (consumer['interface'], consumer['major']) and
                        consumer['accepts_minor'][0] <= producer['minor'] <= consumer['accepts_minor'][1],
                        f'{producer_name} -> {consumer_name}: incompatible interface on {layout["name"]}')
        totals['channel_bytes'] += layout['depth'] * layout['max_payload']
    limits = dict(image_bytes=IMAGE_LIMIT * MAX_SERVICES, arena_bytes=4096 * MAX_SERVICES,
                  requested_stack_bytes=16384 * MAX_SERVICES, host_stack_bytes=HOST_STACK_FLOOR * MAX_SERVICES,
                  handles=MAX_HANDLES * MAX_SERVICES, channel_bytes=CHANNEL_POOL_BYTES)
    if target == 2:
        limits.update(image_bytes=4 * (12288 + 4096), requested_stack_bytes=4 * 4096,
                      host_stack_bytes=4 * 4096)
    if target == 5:
        limits.update(image_bytes=4 * 0x3c00, arena_bytes=1024, requested_stack_bytes=4096, host_stack_bytes=4096, channel_bytes=512)
    if target == 6:
        limits.update(image_bytes=4 * 0x7c00, arena_bytes=4096, requested_stack_bytes=12288, host_stack_bytes=12288, channel_bytes=1024)
    if target in (5, 6):
        # Match the fixed application arena, including headers and alignment.
        # Runtime/RTOS metadata, management storage and library headroom are
        # separately reserved in the base, never borrowed by application state.
        def pool_cost(size):
            return ((size + 15) // 16) * 16 + 16
        totals['static_pool_bytes'] = sum(
            pool_cost(max(512, service['memory']['stack_bytes'])) +
            pool_cost(max(1, service['memory']['arena_bytes'])) +
            (pool_cost(len(service['config']) // 2) if service['config'] else 0)
            for service in services)
        totals['static_pool_bytes'] += sum(
            pool_cost(entry['layout']['depth'] * entry['layout']['max_payload']) +
            (pool_cost(224) if entry['kind'] else 0) for entry in channel_table.values())
        limits['static_pool_bytes'] = 3840 if target == 5 else 8192
        if target == 5: limits['handles'] = 16
    for resource, used in totals.items():
        require(used <= limits[resource], f'{resource}: need {used}, limit {limits[resource]}')
    from micros_tooling.commands.metadata import bind as bind_commands
    from micros_tooling.communication.channel_metadata import bind as bind_ports
    return {'format': 1, 'target': target, 'services': services, 'channel_ports': bind_ports(packages), 'service_commands': bind_commands(packages),
            'channels': [entry['layout'] for _, entry in sorted(channel_table.items())], 'resources': totals}
