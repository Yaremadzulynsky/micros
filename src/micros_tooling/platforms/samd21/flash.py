"""USB base flashing with private preservation of the MKR network settings rows."""
from pathlib import Path
import json
import hashlib
import os
import struct
import zlib
import shutil
import subprocess
import tempfile
import time
import serial
from serial.tools import list_ports
from micros_tooling.storage.packages import PackageError, require
from micros_tooling.storage.store import atomic_write


def valid_settings(data):
    if len(data) != 1024:
        return False
    for offset in (0, 512):
        record = data[offset:offset + 512]
        magic, sequence = struct.unpack_from('<II', record)
        if magic == 0x3257464d and sequence and struct.unpack_from('<I', record, 448)[0] == 0x54494d43:
            if zlib.crc32(record[:304]) == struct.unpack_from('<I', record, 304)[0]:
                return True
    return False


def programmer(command):
    result = subprocess.run(command, capture_output=True, timeout=45, text=True)
    require(result.returncode == 0, 'MKR programmer failed: ' + (result.stdout + result.stderr)[-1200:])


def select_device(port=None, serial_number=None):
    matches = [p for p in list_ports.comports() if p.vid in (0x2341, 0x2a03)
               and p.pid in (0x8054, 0x0054) and (not port or p.device == port)
               and (not serial_number or p.serial_number == serial_number or p.pid == 0x0054)]
    require(len(matches) == 1, 'Select one connected MKR WiFi 1010 for USB base flashing')
    device = matches[0]
    return device


def bossac():
    # Prefer the core's pinned programmer over unrelated versions on PATH:
    # SAMD bootloader offsets differ between BOSSA releases.
    roots = [Path.home() / 'Library/Arduino15', Path.home() / '.arduino15']
    candidates = [root / 'packages/arduino/tools/bossac/1.7.0-arduino3/bossac' for root in roots]
    executable = next((str(p) for p in candidates if p.is_file()), None) or shutil.which('bossac')
    require(executable, 'Install Arduino SAMD core 1.8.13 or put its bossac executable on PATH')
    return executable


def enter_bootloader(device, executable, *, helper_sketch=False):
    connection = None
    try:
        if device.pid == 0x8054 and helper_sketch:
            connection = serial.Serial(device.device, 1200, timeout=.2)
            connection.dtr = False
        elif device.pid == 0x8054:
            from micros_tooling.platforms.samd21.transport import SerialRemote
            remote = SerialRemote(device.device, device.serial_number)
            connection = remote.serial
            try:
                reply = remote.request('BOOTLOADER', allow_error=True)
                require(reply['result'] == 0 or reply.get('message') == 'unknown command',
                        'MKR rejected bootloader entry: ' + str(reply))
                legacy = reply['result'] != 0
            except PackageError as error:
                raise PackageError(
                    'MKR firmware could not enter the USB bootloader. Double-press the board Reset button, '
                    'then rerun enrollment with --rebuild-base to replace an unfinished enrollment with '
                    'firmware from this SDK, or --retry-flash to retry the saved image. '
                    f'Original error: {error}') from error
            except (TimeoutError, json.JSONDecodeError):
                legacy = True  # A stock Arduino sketch has no micros protocol.
            if legacy:
                remote.serial.baudrate = 1200
                remote.serial.dtr = False
        # Closing CDC at 115200 cancels Arduino's pending reset. Keep it open
        # until the bootloader has actually enumerated on this USB location.
        deadline = time.monotonic() + 10
        while True:
            ports = [p for p in list_ports.comports() if p.vid == device.vid and p.pid == 0x0054
                     and p.location == device.location]
            if len(ports) == 1:
                break
            require(time.monotonic() < deadline, 'MKR bootloader did not appear; double-press Reset and retry')
            time.sleep(.2)
    finally:
        if connection:
            connection.close()
    return [executable, '-p', ports[0].device, '-U', 'true']


def erase(port, serial_number=None, log=None):
    """Erase user flash, retaining the 8 KiB Arduino USB bootloader."""
    device = select_device(port, serial_number)
    executable = erase_programmer()
    from micros_tooling.terminal.progress import Activity, run
    with Activity('Entering USB bootloader'):
        command = enter_bootloader(device, executable)
    # No backup, verification read, or reset into the now-empty application.
    run([*command, '-e'], log, timeout=120)


def erase_programmer():
    executable = bossac()
    # Newer BOSSA versions change offset semantics. Do not accidentally erase
    # the USB bootloader by accepting a different system executable.
    help_text = subprocess.run([executable, '--help'], capture_output=True, text=True, timeout=10)
    # Arduino BOSSA returns 1 for --help, even when it prints valid help.
    require(help_text.returncode in (0, 1) and 'keep the 8KB of bootloader for SAM Dxx' in (help_text.stdout + help_text.stderr),
            'SAMD21 erase needs Arduino bossac 1.7.0; install Arduino SAMD core 1.8.13.')
    return executable


def flash(firmware, port=None, serial_number=None, *, preserve_settings=True, settings_override=None, helper_sketch=False):
    device = select_device(port, serial_number)
    executable = bossac()
    base = Path(firmware).with_suffix('.bin').read_bytes()
    from micros_tooling.platforms.samd21.build import base_info
    info=base_info(firmware)
    require(len(base)==info['flash_bytes'] and hashlib.sha256(base).digest()==info['hash'], 'Base BIN does not match ELF')
    ab=info['base_slot'] is not None
    require(not ab or info['base_slot']==0, 'Initial USB A/B installation requires slot A')
    selector=Path(firmware).parent.parent/'selector.bin'
    if ab:
        from micros_tooling.platforms.samd21.layout import migration_image
        migration_image(base,selector.read_bytes(),bytes(1024))
    require(settings_override is None or len(settings_override) == 1024, "MKR settings must be exactly 1024 bytes")
    command = enter_bootloader(device, executable, helper_sketch=helper_sketch)
    # TemporaryDirectory is mode 0700: flash reads include private network credentials.
    with tempfile.TemporaryDirectory(prefix='micros-mkr-flash-') as directory:
        settings = settings_override if settings_override is not None else bytes(1024)
        if preserve_settings and settings_override is None:
            backup = Path(directory) / 'backup.bin'
            programmer([*command, '-r0x1c600', str(backup)])
            previous = backup.read_bytes()
            require(len(previous) == 0x1c600, 'Unexpected bootloader flash geometry')
            settings = previous[0x1c00:0x2000]
            if not valid_settings(settings):settings = previous[0x1c200:0x1c600]
            identity = serial_number or device.serial_number or device.location or device.device
            key = hashlib.sha256(identity.encode()).hexdigest()
            state = Path(os.environ.get('MICROS_STATE_DIR', Path(__file__).resolve().parents[4] / '.micros'))
            recovery = state / 'samd21/recovery' / (key + '.bin')
            if valid_settings(settings):
                atomic_write(recovery, settings)
            elif recovery.is_file() and valid_settings(recovery.read_bytes()):
                settings = recovery.read_bytes()
        if ab:
            image=migration_image(base,selector.read_bytes(),settings)
        else:
            image = bytearray(b'\xff' * (0x1e600 - 0x2000))
            image[:len(base)] = base
            image[0x1e200 - 0x2000:] = settings
        upload = Path(directory) / 'upload.bin'
        upload.write_bytes(image)
        programmer([*command, '-e', '-w', '-v', '-b', '-R', str(upload)])
    deadline = time.monotonic() + 15
    while True:
        ports = [p for p in list_ports.comports() if p.vid == device.vid and p.pid == 0x8054
                 and p.location == device.location
                 and (not (serial_number or device.serial_number) or p.serial_number == (serial_number or device.serial_number))]
        if len(ports) == 1:
            return ports[0].device
        require(time.monotonic() < deadline, 'Verified base did not enumerate; inspect the MKR over USB')
        time.sleep(.2)
