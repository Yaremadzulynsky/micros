"""Bounded base-only OTA over the existing direct/relay management connection."""
import hashlib
import http.client
import struct
import time
from pathlib import Path
from micros_tooling.storage.packages import PackageError, require
from micros_tooling.config.resources import verify_board_firmware
from micros_tooling.communication.remote import RemoteRejected

CHUNK_BYTES = 4096


def request_when_ready(remote, method, path, body=b'', *, sleep=time.sleep):
    """503 means the controller/relay rejected admission; no command ran.

    Do not retry lost replies, conflicts, or 504 (unknown execution outcome).
    Eight bounded attempts fit within the existing 60-second deployment lease.
    """
    for attempt in range(8):
        try:
            return remote.request(method, path, body)
        except RemoteRejected as error:
            if error.status != 503 or attempt == 7:
                raise
            sleep(min(0.25 * (2 ** attempt), 2))


def inspect_base(remote, firmware, image=None):
    """Validate the target ELF/BIN and hardware before acquiring a mutation lease."""
    from elftools.elf.elffile import ELFFile
    firmware = Path(firmware)
    image = Path(image) if image else firmware.with_suffix('.bin')
    with firmware.open('rb') as stream:
        elf = ELFFile(stream)
        table = elf.get_section_by_name('.symtab')
        symbols = table.get_symbol_by_name('micros_base_ota_version') if table else None
        require(symbols, 'Target base is not OTA-capable. Build with --ota.')
        symbol = symbols[0]
        section = elf.get_section(symbol['st_shndx'])
        offset = symbol['st_value'] - section['sh_addr']
        require(section.data()[offset:offset+4] == struct.pack('<I', 1), 'Unsupported base OTA version')
    before = remote.status()
    ota = before.get('base_ota', {})
    require(ota.get('version') == 1, 'Installed base lacks OTA. Install the A/B layout over USB first.')
    require(not ota.get('pending') and not ota.get('uploading'), 'Another base update is active.')
    require(not before['activation']['pending'] and not before.get('physical_recovery'),
            'Application trial or physical recovery is active.')
    flash_mb = before.get('board', {}).get('flash_mb')
    require(flash_mb in (4, 8), 'Board must report its physical flash size.')
    verify_board_firmware(dict(flash_mb=flash_mb), firmware)
    require(type(ota.get('slot_bytes')) is int and 288 <= image.stat().st_size <= ota['slot_bytes'],
            'Base image exceeds the inactive OTA slot.')
    payload = image.read_bytes()
    base_hash = hashlib.sha256(firmware.read_bytes()).hexdigest()
    # ESP32 image header + first segment header (32 bytes), then esp_app_desc_t.
    require(payload[0] == 0xe9 and payload[32:36] == struct.pack('<I', 0xabcd5432)
            and payload[176:208] == bytes.fromhex(base_hash), 'BIN does not match the supplied base ELF.')
    require(before['identity']['base_sha256'] != base_hash, 'This exact base is already installed.')
    return dict(before=before, payload=payload, base_sha256=base_hash,
                image_sha256=hashlib.sha256(payload).hexdigest(), image_bytes=len(payload))


def update_base(remote, firmware, image=None, *, dry_run=False, progress=None,
                clock=time.monotonic, sleep=time.sleep):
    request = lambda method, path, body=b'': request_when_ready(remote, method, path, body, sleep=sleep)
    prepared = inspect_base(remote, firmware, image)
    before, payload = prepared['before'], prepared['payload']
    summary = {key: prepared[key] for key in ('base_sha256', 'image_sha256', 'image_bytes')}
    if dry_run:
        return dict(**summary, dry_run=True, slot_bytes=before['base_ota']['slot_bytes'])
    emit = progress or (lambda phase, message: None)
    with remote.deployment_session(before):
        # The selection lease is shared with application deployment; identity is
        # checked again because the same application can survive a base reboot.
        current = remote.status()
        require(current['identity'] == before['identity'], 'Base changed during preparation.')
        request('POST', '/v1/base-begin',
                       struct.pack('<4sI32s', b'MBO1', len(payload), bytes.fromhex(prepared['image_sha256'])))
        try:
            last_report = -1
            for offset in range(0, len(payload), CHUNK_BYTES):
                request('PUT', f'/v1/base-chunk?cursor={offset}', payload[offset:offset+CHUNK_BYTES])
                percent = min(100, (offset+CHUNK_BYTES)*100//len(payload))
                if percent//10 != last_report:
                    emit('upload', f'Base image: {percent}%')
                    last_report = percent//10
        except (OSError, http.client.HTTPException, PackageError):
            # Never replay an uncertain chunk or switch boot selection on error.
            try:
                request('POST', '/v1/base-abort')
            except (OSError, http.client.HTTPException, PackageError):
                pass
            raise
        emit('trial', 'Booting the new base; application packages remain untouched and stopped.')
        try:
            request('POST', '/v1/base-finish')
        except (OSError, http.client.HTTPException, PackageError):
            pass  # Boot may precede receipt of the reply. Observe, never repeat finish.
    deadline = clock() + before['base_ota']['trial_seconds'] + 30
    saw_candidate = False
    while clock() < deadline:
        try:
            status = remote.status()
            require(status['identity']['device_id'] == before['identity']['device_id'], 'Device identity changed.')
            actual = status['identity']['base_sha256']
            if actual == prepared['base_sha256']:
                saw_candidate = True
                require(status.get('base_ota', {}).get('version') == 1, 'Candidate has no OTA support.')
                if status['uptime_us'] < 5_000_000:
                    sleep(1)
                    continue
                if status['base_ota']['pending']:
                    with remote.deployment_session(status):
                        request('POST', '/v1/base-confirm', bytes.fromhex(actual))
                    # Verify acknowledgement against a fresh device observation.
                    continue
                emit('confirmed', 'Base confirmed. Build and deploy applications against the new ELF.')
                return dict(**summary, confirmed=True, status=status)
            if saw_candidate and actual == before['identity']['base_sha256']:
                raise PackageError('Base rolled back; previous base is running.')
        except RemoteRejected as error:
            if error.status not in (409, 503, 504):
                raise
        except (OSError, http.client.HTTPException):
            pass
        sleep(1)
    raise PackageError('Base update not confirmed. Inspect status; an unconfirmed candidate rolls back on reset.')
