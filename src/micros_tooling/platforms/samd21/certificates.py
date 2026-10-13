"""Provision the selected server trust bundle in NINA, restoring the SAMD base."""
import hashlib
import io
import platform
import re
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from serial.tools import list_ports

from micros_tooling.storage.packages import require
from micros_tooling.storage.store import atomic_write

VERSION = '2.4.0'
# Arduino release checksums: https://github.com/arduino/arduino-fwuploader/releases/tag/2.4.0
ARCHIVES = {
    ('Darwin', 'arm64'): ('macOS_ARM64', '6ba5f8562df74721563ba7e1f0b2a64398abcc11a7ed37864e83a61d2bd7ac26'),
    ('Darwin', 'x86_64'): ('macOS_64bit', 'f948545aaa1cda145516637b88bf51221a8a532393c80e831a31c4f62a305738'),
    ('Linux', 'x86_64'): ('Linux_64bit', '50c21df34438bc306435374da251c2329d80af113e48f61d517a0985005d4815'),
    ('Linux', 'aarch64'): ('Linux_ARM64', '3d67ea645bef96b47d7496fb150a00ccecd3b15bb54c333b451199e62ec62e56'),
    ('Linux', 'armv7l'): ('Linux_ARMv7', '25ca318b1b75b1a886cd63238de0bd091181474e2f8bd90cd747240cb756bec9'),
}


def prepare_bundle(certificate, destination):
    raw = Path(certificate).read_bytes()
    require(b'PRIVATE KEY' not in raw, 'The NINA trust bundle must contain only public certificates.')
    blocks = re.findall(rb'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', raw, re.S)
    require(blocks and not re.sub(rb'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', b'', raw, flags=re.S).strip(),
            'The server trust file must be a PEM certificate bundle.')
    unique = list(dict.fromkeys(blocks))
    bundle = b'\n'.join(unique) + b'\n'
    # Leave room for the uploader's index in NINA's 128 KiB partition.
    require(len(bundle) <= 96 * 1024 and len(unique) <= 64,
            'Server certificate bundle exceeds the MKR NINA trust budget (96 KiB / 64 certificates).')
    for block in unique:
        parsed = subprocess.run(['openssl', 'x509', '-noout'], input=block + b'\n', capture_output=True, timeout=10)
        require(parsed.returncode == 0, 'Invalid certificate in the server trust bundle.')
    atomic_write(destination, bundle)
    return hashlib.sha256(bundle).hexdigest()


def uploader(root):
    key = (platform.system(), platform.machine())
    require(key in ARCHIVES, 'Automatic MKR certificates need macOS or Linux on a supported host architecture.')
    label, checksum = ARCHIVES[key]
    directory = root / 'build/toolchains' / ('arduino-fwuploader-' + VERSION)
    archive = directory / (label + '.tar.gz')
    if not archive.is_file():
        url = f'https://github.com/arduino/arduino-fwuploader/releases/download/{VERSION}/arduino-fwuploader_{VERSION}_{label}.tar.gz'
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read(40 * 1024 * 1024 + 1)
        require(hashlib.sha256(data).hexdigest() == checksum, 'Arduino firmware uploader checksum mismatch.')
        atomic_write(archive, data)
    data = archive.read_bytes()
    require(hashlib.sha256(data).hexdigest() == checksum, 'Cached Arduino firmware uploader checksum mismatch.')
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as packed:
        entries = [m for m in packed.getmembers() if m.isfile() and Path(m.name).name == 'arduino-fwuploader']
        require(len(entries) == 1, 'Arduino firmware uploader archive has an unexpected layout.')
        binary = packed.extractfile(entries[0]).read()
    executable = directory / label / 'arduino-fwuploader'
    atomic_write(executable, binary)
    executable.chmod(0o700)
    return executable


def restore(port, firmware, serial_number, state, receipt, save):
    """A pending helper upload never qualifies as a reusable micros base."""
    from .flash import flash
    if not receipt.get('nina_restore_pending'):
        return port
    settings = (state.root / 'nina-settings.bin').read_bytes()
    port = flash(firmware, port, serial_number, preserve_settings=False,
                 settings_override=settings, helper_sketch=True)
    receipt['nina_restore_pending'] = False
    save()
    return port


def provision(port, firmware, serial_number, certificate, state, receipt, save):
    from micros_tooling.deployment import enrollment as e
    from .flash import select_device, enter_bootloader, bossac, programmer, valid_settings
    bundle = state.root / 'nina-trust.pem'
    fingerprint = prepare_bundle(certificate, bundle)
    if receipt.get('nina_trust_sha256') == fingerprint and not receipt.get('nina_restore_pending'):
        return port, False
    executable = uploader(e.ROOT)
    e.progress('Installing server certificates in NINA (replaces its trust store)…')
    device = select_device(port, serial_number)
    command = enter_bootloader(device, bossac(), helper_sketch=bool(receipt.get('nina_restore_pending')))
    # Only the first 8 KiB of application flash are read to retain the two
    # settings rows. No application/firmware flash backup is made.
    if not receipt.get('nina_restore_pending'):
        with tempfile.TemporaryDirectory(prefix='micros-nina-settings-') as temporary:
            snapshot = Path(temporary) / 'settings-window.bin'
            programmer([*command, '-r0x2000', str(snapshot)])
            raw = snapshot.read_bytes()
            require(len(raw) == 0x2000, 'MKR settings read returned an unexpected size.')
            settings = raw[0x1c00:0x2000]
            atomic_write(state.root / 'nina-settings.bin', settings if valid_settings(settings) else bytes(1024))
    receipt['nina_restore_pending'] = True
    save()
    try:
        e.run_tool([str(executable), 'certificates', 'flash', '--fqbn', 'arduino:samd:mkrwifi1010',
                    '--address', command[2], '--file', str(bundle)], state.root / 'nina-certificates.log', timeout=300)
    finally:
        # The helper uses normal Arduino 1200-baud reset, not the micros RPC.
        matches = [p for p in list_ports.comports()
                   if p.vid == device.vid and p.pid in (0x8054, 0x0054) and p.location == device.location]
        require(len(matches) == 1, 'Reconnect the same MKR and rerun enroll to restore its base after certificate provisioning.')
        port = restore(matches[0].device, firmware, serial_number, state, receipt, save)
    receipt['nina_trust_sha256'] = fingerprint
    save()
    return port, True
