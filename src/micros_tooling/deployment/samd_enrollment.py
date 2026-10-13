"""MKR WiFi 1010 enrollment using its SAM-BA bootloader and NINA identity."""
import json
import re
import shutil
import secrets
import sys
import time
from pathlib import Path

from serial.tools import list_ports
from micros_tooling.storage.packages import require, digest
from micros_tooling.storage.workspace import Workspace
from micros_tooling.terminal.progress import Activity


def is_mkr(port):
    return any(p.device == port and p.vid in (0x2341, 0x2a03) and p.pid in (0x8054, 0x0054)
               for p in list_ports.comports())


def prepare_tools(session, compiler_dir=None):
    """Install pinned sources and validate host tools without touching a board."""
    from micros_tooling.deployment import enrollment as e
    session.mkdir(parents=True, exist_ok=True)
    compiler = str(compiler_dir / 'arm-none-eabi-gcc') if compiler_dir else shutil.which('arm-none-eabi-gcc')
    candidates = ([Path(compiler).parent] if compiler else [])
    if compiler_dir is None:
        candidates.append(Path('/opt/gcc-arm-none-eabi-10-2020-q4-major/bin'))
    compiler = next((p for p in candidates if all((p / ('arm-none-eabi-' + tool)).is_file()
                     for tool in ('gcc', 'g++', 'objcopy'))), None)
    require(compiler is not None, 'MKR setup needs a complete ARM GCC 10+ toolchain (gcc, g++, objcopy) on PATH.')
    version = e.run_tool([str(compiler / 'arm-none-eabi-gcc'), '-dumpversion']).strip()
    require(int(version.split('.')[0]) >= 10, 'MKR setup requires ARM GCC 10 or newer.')
    require(shutil.which('arduino-cli'), 'MKR setup needs arduino-cli on PATH.')
    core = [Path.home() / 'Library/Arduino15', Path.home() / '.arduino15']
    if not any((p / 'packages/arduino/hardware/samd/1.8.13').is_dir() for p in core):
        e.run_tool(['arduino-cli', 'core', 'update-index'], session / 'setup.log', timeout=600)
        e.run_tool(['arduino-cli', 'core', 'install', 'arduino:samd@1.8.13'], session / 'core.log', timeout=1200)
    dependencies = [('freertos-kernel-v11.1.0', 'V11.1.0', 'FreeRTOS/FreeRTOS-Kernel', 'dbf70559b27d39c1fdb68dfb9a32140b6a6777a0'),
                    ('wifinina-1.8.14', '1.8.14', 'arduino-libraries/WiFiNINA', '0de2f03e4ea4e0ced5342153ae77ac1f2cf1afd5')]
    for name, tag, repo, revision in dependencies:
        destination = e.ROOT / 'build/toolchains' / name
        if not destination.exists():
            e.run_tool(['git', 'clone', '--depth', '1', '--branch', tag, f'https://github.com/{repo}.git', str(destination)], session / (name + '.log'), timeout=600)
        require(e.run_tool(['git', '-C', str(destination), 'rev-parse', 'HEAD']).strip() == revision,
                f'{name} does not match its pinned revision; it was left unchanged.')
    return compiler


def prepare(session, args):
    from micros_tooling.deployment import enrollment as e
    from micros_tooling.platforms.samd21.build import base_info
    if args.firmware:
        firmware = args.firmware.resolve()
    else:
        compiler = prepare_tools(session)
        output = session / 'base'
        e.run_tool([sys.executable, str(e.ROOT / 'src/micros_tooling/platforms/build_samd21.py'),
                    '--compiler-dir', str(compiler), '--output', str(output)], session / 'prepare.log', timeout=1800)
        firmware = output / 'firmware/runtime.ino.elf'
    info = base_info(firmware)
    require(info['base_slot'] == 0, 'MKR enrollment requires a slot A base and its selector.bin.')
    require(digest(firmware.with_suffix('.bin').read_bytes()) == info['hash'].hex(), 'MKR binary does not match its ELF.')
    require((firmware.parent.parent / 'selector.bin').is_file(), 'MKR base is missing selector.bin.')
    from micros_tooling.platforms.samd21.layout import migration_image
    migration_image(firmware.with_suffix('.bin').read_bytes(),
                    (firmware.parent.parent / 'selector.bin').read_bytes(), bytes(1024))
    return dict(firmware=str(firmware), base_sha256=info['hash'].hex(),
                selector_sha256=digest((firmware.parent.parent / 'selector.bin').read_bytes()))


def read_identity(port):
    from micros_tooling.platforms.samd21.transport import SerialRemote
    with SerialRemote(port) as remote:
        deadline = time.monotonic() + 15
        while True:
            status = remote.status()
            device_id = status['identity']['device_id']
            if re.fullmatch('[0-9a-f]{12}', device_id) and device_id != '000000000000':
                return device_id, status['base_sha256']
            require(time.monotonic() < deadline, 'MKR Wi-Fi module did not provide its identity; inspect NINA firmware.')
            time.sleep(.2)


def enroll_mkr(args, port, operator, workspace, remote, roster):
    from micros_tooling.deployment import enrollment as e
    from micros_tooling.communication.discovery import probe
    from micros_tooling.fleet.server import configured_remote
    from micros_tooling.platforms.samd21.flash import flash
    from micros_tooling.platforms.samd21.certificates import provision
    device = next(p for p in list_ports.comports() if p.device == port)
    with Activity('Identifying MKR WiFi 1010'):
        detected = probe(dict(port=port), timeout=3) if device.pid == 0x8054 else {}
    device_id = detected.get('device_id')
    require(not any(d['device_id'] == device_id for d in roster), 'This controller is already enrolled.')
    e.progress('Detected Arduino MKR WiFi 1010 · SAMD21G18A · 256 KiB flash' + (f' · {device_id}' if device_id else ' · Wi-Fi identity available after firmware installation'))
    if args.detect:
        return dict(platform='samd21', device_id=device_id, port=port, message='Arduino MKR WiFi 1010 · SAMD21G18A · 256 KiB flash')
    # A stock sketch has no NINA identity protocol. Keep preparation bound to the
    # selected physical USB location, not a made-up MAC or another attached MKR.
    key = digest((device.location or device.serial_number or port).encode())[:24]
    state = Workspace(operator / 'onboarding' / ('mkr-usb-' + key))
    with state.locked():
        receipt = state.read('enrollment.json', {})
        require(not device_id or not receipt.get('board') or receipt['board']['device_id'] == device_id,
                'A different MKR is connected at this USB location; preserve its enrollment session.')
        name = receipt.get('name') or args.name
        if not name:
            require(e.interactive(args), 'Supply a board name: micros enroll NAME --port PORT')
            name = input('Board name: ').strip()
        require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,79}', name), 'Invalid board name.')
        require(not any(d['name'] == name for d in roster), 'That name belongs to an enrolled controller.')
        require(not args.name or args.name == name, 'This pending enrollment has a different name.')
        require(not receipt.get('nina_restore_pending') or not getattr(args, 'rebuild_base', False),
                'Rerun enroll without --rebuild-base first to restore the base after interrupted NINA provisioning.')
        if getattr(args, 'rebuild_base', False):
            require(receipt and not receipt.get('confirmed'),
                    '--rebuild-base requires an unfinished enrollment; confirmed controllers must use the normal update workflow.')
            state.write(Path('enrollment-history') / (secrets.token_hex(8) + '.json'), receipt)
            receipt = dict(name=name, **({'board': receipt['board']} if receipt.get('board') else {}))
            e.progress('Preserved the previous enrollment attempt; preparing a new base from this SDK.')
        receipt['name'] = name
        def save():
            state.write('enrollment.json', receipt)
        save()
        board = None
        try:
            if not receipt.get('firmware'):
                e.progress('Preparing a management-only SAMD21 base…')
                session = state.root / 'installations' / secrets.token_hex(8)
                receipt.update(prepare(session, args))
                save()
            from micros_tooling.platforms.samd21.build import base_info
            firmware = Path(receipt['firmware'])
            require(base_info(firmware)['hash'].hex() == receipt['base_sha256'], 'Prepared MKR base changed.')
            require(digest((firmware.parent.parent / 'selector.bin').read_bytes()) == receipt['selector_sha256'], 'Prepared MKR selector changed.')
            require(not args.firmware or args.firmware.resolve() == firmware.resolve(), 'Resume with the same prepared MKR firmware.')
            # Verify the physical runtime before reusing a completed USB write.
            reuse = False
            if receipt.get('flash_started') and device_id and not receipt.get('nina_restore_pending'):
                with Activity('Checking installed MKR firmware'):
                    observed_id, observed_base = read_identity(port)
                reuse = observed_base == receipt['base_sha256'] and observed_id == device_id
            require(not receipt.get('flash_started') or reuse or args.retry_flash or receipt.get('nina_restore_pending'),
                    'Previous MKR flash outcome is unknown. Inspect the controller and use --retry-flash to retry.')
            receipt['flash_started'] = True
            save()
            port, installed = provision(port, firmware, device.serial_number, operator / 'servercert.pem', state, receipt, save)
            if not reuse and not installed:
                with Activity('Writing SAMD21 firmware'):
                    port = flash(firmware, port, device.serial_number, preserve_settings=False)
            with Activity('Reading MKR Wi-Fi identity'):
                observed_id, observed_base = read_identity(port)
            require(not device_id or observed_id == device_id, 'MKR identity changed during installation.')
            require(observed_base == receipt['base_sha256'], 'MKR did not start the prepared firmware.')
            board = dict(platform='samd21', chip='SAMD21G18A', device_id=observed_id, flash_mb=.25)
            receipt.update(board=board, flashed=True)
            remote = configured_remote(workspace, observed_id)
            roster = json.loads(remote.raw('GET', '/v1/devices'))['devices']
            require(not any(d['device_id'] == observed_id for d in roster), 'This controller is already enrolled; enrollment was not changed.')
            receipt['pending_enrollment'] = True
            receipt['confirmed'] = False
            save()
            relay = e.credentials(operator, workspace, remote, board, name, roster, args.relay_credentials)
            e.connect_wifi(board, port, args, receipt, relay, save)
            e.verify_console(remote, board, receipt['base_sha256'])
            receipt.update(confirmed=True, pending_enrollment=False)
            save()
            return dict(device_id=observed_id, name=name, platform='samd21', online=True, session=str(state.root),
                        message=f'{name} is online in the console. SAMD21 firmware and connection verified.')
        except KeyboardInterrupt:
            raise e.EnrollmentCancelled(e.cancel_enrollment(remote, board, receipt, save) if board else 'Enrollment canceled.') from None
        except Exception:
            if board and receipt.get('pending_enrollment'):
                result = e.cancel_enrollment(remote, board, receipt, save)
                if 'could not be confirmed' in result:
                    e.progress(result)
            raise
