"""One resumable USB-to-console enrollment, independent of application recipes."""
import argparse
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
from urllib.parse import urlsplit

from micros_tooling.storage.packages import PackageError, digest, require
from micros_tooling.storage.store import atomic_write
from micros_tooling.storage.workspace import Workspace
from micros_tooling.terminal.progress import Activity

ROOT = Path(__file__).resolve().parents[3]


def add_parser(commands):
    p = commands.add_parser('enroll', help='detect a USB board, flash micros, set Wi-Fi and verify the console')
    p.add_argument('name', nargs='?', help='console name; existing enrollment names are preserved')
    p.add_argument('--port', help='USB serial port; prompt if several physical boards are connected')
    p.add_argument('--server', help='saved server profile; otherwise choose before connecting')
    p.add_argument('--detect', action='store_true', help='identify chip, MAC and flash only (USB probing resets the board)')
    p.add_argument('--ssid', help='2.4 GHz network name; otherwise prompt or keep working saved Wi-Fi')
    pw = p.add_mutually_exclusive_group()
    pw.add_argument('--password-file', type=Path)
    pw.add_argument('--open-network', action='store_true')
    p.add_argument('--firmware', type=Path, help='ESP8266 or MKR base ELF in a complete prepared flash directory')
    p.add_argument('--relay-credentials', type=Path, help='existing enrollment directory when recovering private state')
    p.add_argument('--yes', action='store_true', help=argparse.SUPPRESS)
    p.add_argument('--retry-flash', action='store_true', help='explicitly retry an interrupted flash after inspecting its saved log')
    p.add_argument('--rebuild-base', action='store_true', help='archive an unfinished ESP8266 enrollment and rebuild firmware after an SDK fix')
    p.add_argument('--json', action='store_true', help='machine-readable result; no interactive prompts')
    return p


def progress(message):
    from micros_tooling.terminal.progress import message as display
    display(message)


def interactive(args):
    return not args.json and sys.stdin.isatty()


def resumable(receipt, existing):
    """An online board may have connected just before enrollment was interrupted."""
    if not (receipt and not receipt.get('confirmed') and receipt.get('flashed')
            and isinstance(receipt.get('base_sha256'), str)
            and re.fullmatch('[0-9a-f]{64}', receipt.get('base_sha256', ''))
            and receipt.get('board', {}).get('device_id') == existing['device_id']
            and receipt.get('name') == existing['name']):
        return False
    observed = ((existing.get('status') or {}).get('identity') or {}).get('base_sha256')
    return not observed or observed == receipt['base_sha256']


def valid_board_name(name, roster, device_id):
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,79}', name),
            'Use a board name containing letters, digits, spaces, dots, underscores or hyphens.')
    require(not any(d['name'] == name and d['device_id'] != device_id for d in roster),
            'That name belongs to another board; choose a different name.')
    return name


def choose_port(args, roster=None):
    from serial.tools import list_ports
    from micros_tooling.communication.wifi import USB_VENDORS
    if args.port:
        return args.port
    ports = {}
    for p in sorted(list_ports.comports(), key=lambda p: ('SLAB' in p.device, p.device)):
        if p.vid is not None:
            # Do not merge two adapters just because both report serial "0001".
            key = (p.vid, p.pid, p.location) if p.location else p.device
            ports.setdefault(key, p)
    choices = list(ports.values())
    require(choices, 'No supported USB controller found. Plug it in, or use --port PORT.')
    if len(choices) == 1 and roster is None and choices[0].vid in USB_VENDORS:
        return choices[0].device
    require(interactive(args), ('Several boards are connected; select --port PORT: ' if len(choices) > 1 else 'Select --port PORT: ') + ', '.join(p.device for p in choices))
    from micros_tooling.communication.discovery import discover, describe, operation_blocker
    progress('Discovering controllers; ROM probing resets interfaces without a micros reply…')
    with Activity('Identifying connected controllers'):
        found = {item['port']: item for item in discover()}
    enrolled = {d['device_id']: d for d in (roster or [])}
    operation = getattr(args, 'command', 'enroll')
    operator = None
    if enrolled and operation == 'enroll':
        from micros_tooling.storage.client import operator_directory
        operator = operator_directory(Workspace(Path(os.environ.get('MICROS_STATE_DIR', ROOT / '.micros'))))
    available = []
    for p in choices:
        result = found.get(p.device, {})
        detail = describe(result, operation) if result else 'unidentified'
        existing = enrolled.get(result.get('device_id'))
        resume = False
        if existing and operation == 'enroll':
            try:
                saved = Workspace(operator / 'onboarding' / existing['device_id']).read('enrollment.json', {})
                resume = resumable(saved, existing)
            except (OSError, ValueError):
                pass
        blocker = operation_blocker(result, operation)
        if p.vid in (0x2341, 0x2a03) and p.pid not in (0x8054, 0x0054):
            blocker = f'{operation} not supported yet for this board'
        if blocker:
            progress(f'— {p.device}: {detail}' + ('' if blocker in detail else f' · {blocker}'))
        elif existing and not resume:
            progress(f'— {p.device}: {detail} · {existing["name"]} · already enrolled')
        else:
            available.append(p)
            progress(f'{len(available)}. {p.device}: {detail}' + (' · resume unfinished enrollment' if resume else ''))
    require(available, f'No controllers available to {operation}. See the reason beside each connected interface.')
    from micros_tooling.deployment.server_selection import prompt
    def controller_number(choice):
        require(choice.isdigit() and 1 <= int(choice) <= len(available), 'Choose a displayed available controller number, or q to cancel.')
        return int(choice) - 1
    return available[prompt(f'Select controller to {operation}', controller_number)].device


def esptool():
    import importlib.util
    if importlib.util.find_spec('esptool') is not None:
        return [sys.executable, '-m', 'esptool']
    executable = shutil.which('esptool.py') or shutil.which('esptool')
    if executable:
        return [executable]
    # The ESP32 setup installs esptool in its isolated IDF environment.
    candidates = sorted((Path.home() / '.espressif/python_env').glob('*/bin/esptool.py'))
    require(candidates, 'esptool is missing. Install it with python3 -m pip install esptool, then rerun micros enroll.')
    return [str(candidates[-1])]


def run_tool(command, log=None, timeout=120):
    from micros_tooling.terminal.progress import run
    return run(command, log, timeout)


def parse_probe(output, enforce_support=True):
    # Both esptool v4 and v5 labels; USB VID/PID is never treated as chip proof.
    chip = re.search(r'Chip (?:is|type:)\s*(ESP[0-9A-Za-z_-]+)', output, re.I)
    mac = re.findall(r'MAC:\s*([0-9a-f:]{17})', output, re.I)
    size = re.search(r'Detected flash size:\s*(\d+)\s*MB', output, re.I)
    require(chip and mac and size, 'Could not identify chip, MAC and flash capacity. Check USB/boot mode and retry; no firmware was written.')
    label = chip[1].upper()
    original_esp32 = label == 'ESP32' or label.startswith(('ESP32-D0WD', 'ESP32-D2WD', 'ESP32-PICO', 'ESP32-U4WDH', 'ESP32-S0WD'))
    platform = 'esp8266' if label in ('ESP8266', 'ESP8266EX') else 'esp32' if original_esp32 else None
    if enforce_support:
        require(platform, f'Detected {label}, but this wizard only has bases for original ESP32 and ESP8266. No firmware was written.')
    flash_mb = int(size[1])
    if enforce_support:
        require(flash_mb in ((4,) if platform == 'esp8266' else (4, 8)), f'{label} with {flash_mb} MiB flash is not a supported base layout.')
    return dict(platform=platform or label.lower().replace('-', ''), chip=label, device_id=mac[-1].lower().replace(':', ''), flash_mb=flash_mb)


def probe(port):
    progress('Detecting the chip and flash over USB (this resets the selected board)…')
    return parse_probe(run_tool([*esptool(), '--port', port, 'flash_id'], timeout=45))


def check_identity(expected, observed):
    require(all(expected[k] == observed[k] for k in ('platform', 'device_id', 'flash_mb')),
            'The connected board or flash capacity changed; refusing to continue this enrollment.')


def credentials(operator, workspace, remote, board, name, roster, explicit=None):
    existing = next((d for d in roster if d['device_id'] == board['device_id']), None)
    destination = operator / 'enrollments' / board['device_id']
    candidates = [destination, workspace.root / 'server/enrollments' / board['device_id'],
                  ROOT / '.micros/server/enrollments' / board['device_id']]
    if explicit:
        candidates.insert(0, explicit)
    source = next((p for p in candidates if (p / 'relay.token').is_file()), None)
    require(not existing or source, 'This board is already enrolled, but its private enrollment token is unavailable. Recover its enrollment directory with --relay-credentials PATH; enrollment will not be reset.')
    config = json.loads((operator / 'client.json').read_text())
    url = config.get('device_url', config['url'])
    origin = urlsplit(url)
    require(origin.scheme == 'https' and origin.hostname and origin.path in ('', '/') and not origin.username and not origin.query and not origin.fragment,
            'Configure a valid HTTPS device_url in the operator configuration.')
    cert = (operator / 'servercert.pem').read_bytes()
    if source:
        require((source / 'relay-ca.pem').read_bytes() == cert, 'Saved enrollment belongs to another server certificate.')
        token = (source / 'relay.token').read_text().strip()
    else:
        token = secrets.token_hex(32)
    require(re.fullmatch('[0-9a-f]{64}', token), 'Invalid private enrollment token.')
    # Persist before the idempotent server request, including its exact name.
    atomic_write(destination / 'relay.token', token.encode())
    atomic_write(destination / 'relay-ca.pem', cert)
    atomic_write(destination / 'server.json', json.dumps(dict(url=url)).encode())
    remote.raw('POST', '/v1/enroll', json.dumps(dict(device_id=board['device_id'], name=name, token=token)).encode())
    return destination


def prepare(board, args, session, relay, remote=None):
    if board['platform'] == 'esp32':
        require(not args.firmware, '--firmware is currently for ESP8266; ESP32 enrollment builds its private console-enabled base.')
        from micros_tooling.platforms.esp32.bootstrap import ready
        if not ready():
            progress('Installing the pinned ESP32 build tools (first-time setup or repair)…')
            run_tool([sys.executable, '-m', 'micros_tooling.platforms.esp32.bootstrap'],
                     session / 'setup.log', timeout=1800)
        from micros_tooling.deployment.onboarding import onboard
        unit = session / (board['device_id'] + '.toml')
        atomic_write(unit, (f'[unit]\ndevice_id = "{board["device_id"]}"\n[board]\nprofile = "esp32_enrollment"\nflash_mb = {board["flash_mb"]}\nrecovery_button = ""\n[services]\n').encode())
        profile_name = 'board-' + board['device_id']
        options = argparse.Namespace(name=profile_name, phase='prepare', credentials=None, rotate_identity=False,
                                     project=unit, board=None, relay_credentials=relay, artifact_remote=remote)
        state = Workspace(session / 'workspace')
        onboard(state, options, lambda phase, message: progress(message))
        base = state.root / 'onboarding' / profile_name / 'base'
        firmware = base / 'micros_runtime.elf'
        manifest = json.loads((base / 'flasher_args.json').read_text())
        files = [(int(offset, 0), base / path) for offset, path in manifest['flash_files'].items()]
        settings = manifest.get('flash_settings', {})
        flash_args = ['--flash_mode', settings.get('flash_mode', 'dio'), '--flash_freq', settings.get('flash_freq', '40m'), '--flash_size', f'{board["flash_mb"]}MB']
    else:
        from micros_tooling.platforms.esp8266.firmware import bind
        firmware = args.firmware.resolve() if args.firmware else session / 'base/micros_esp8266.elf'
        if not args.firmware:
            if not ((ROOT / 'build/toolchains/esp8266-rtos-sdk-v3.4').is_dir() and
                    (ROOT / 'build/toolchains/xtensa-lx106-elf/bin/xtensa-lx106-elf-gcc').is_file() and
                    (ROOT / 'build/esp8266/python/bin/python').is_file()):
                progress('Installing the pinned ESP8266 build tools (first-time setup)…')
                run_tool([sys.executable, '-m', 'micros_tooling.platforms.esp8266.bootstrap'],
                         session / 'setup.log', timeout=1800)
            run_tool([sys.executable, str(ROOT / 'src/micros_tooling/platforms/build_esp8266.py'), '--output', str(firmware.parent),
                      '--relay-ca', str(relay / 'relay-ca.pem')], session / 'prepare.log', timeout=1800)
        bind(firmware)
        import struct, zlib
        prefix = struct.pack('<6I', 0x3642544D, 1, 0, 0xFFFFFFFF, 0xFFFFFFFF, 0)
        journal = prefix + struct.pack('<II', zlib.crc32(prefix), 0x54494D43)
        record = session / 'boot-state-initial.bin'
        atomic_write(record, journal + b'\xff' * (8192 - len(journal)))
        files = [(0, firmware.parent / 'bootloader/bootloader.bin'), (0x8000, firmware.parent / 'partition_table/partition-table.bin'),
                 (0x10000, firmware.with_suffix('.bin')), (0x100000, record)]
        flash_args = ['--flash_mode', 'dio', '--flash_freq', '40m', '--flash_size', '4MB']
    require(all(p.is_file() for _, p in files), 'A complete base directory with bootloader and partition table is required.')
    # Keep reviewed bytes privately; subsequent builds cannot silently change them.
    frozen = []
    for offset, path in sorted(files):
        data = path.read_bytes()
        require(offset >= 0 and offset + len(data) <= board['flash_mb'] * 1048576, 'Base image exceeds detected flash.')
        target = session / 'images' / f'{offset:08x}.bin'
        atomic_write(target, data)
        frozen.append(dict(offset=offset, path=str(target), sha256=digest(data)))
    for a, b in zip(frozen, frozen[1:]):
        require(a['offset'] + Path(a['path']).stat().st_size <= b['offset'], 'Prepared flash images overlap.')
    saved_elf = session / 'images/base.elf'
    atomic_write(saved_elf, firmware.read_bytes())
    if board['platform'] == 'esp8266':
        atomic_write(saved_elf.with_suffix('.bin'), firmware.with_suffix('.bin').read_bytes())
    return dict(firmware=str(saved_elf), base_sha256=digest(saved_elf.read_bytes()), files=frozen, flash_args=flash_args)


def install(board, port, session, receipt, save, retry=False):
    check_identity(board, probe(port))
    require(digest(Path(receipt['firmware']).read_bytes()) == receipt['base_sha256'], 'Prepared ELF changed; preserve this session and restore its exact artifact.')
    for image in receipt['files']:
        require(digest(Path(image['path']).read_bytes()) == image['sha256'], 'Prepared flash image changed; refusing to flash.')
    command = [*esptool(), '--chip', board['platform'], '--port', port, '--baud', '115200']
    images = [v for image in receipt['files'] for v in (hex(image['offset']), image['path'])]
    if receipt.get('flash_started') and not retry:
        # A process could have exited after a successful write but before saving its receipt.
        try:
            run_tool([*command, 'verify_flash', *images], session / 'verify-flash.log', timeout=600)
        except PackageError:
            raise PackageError(f'Previous flash outcome is incomplete or unknown. Inspect {session / "verify-flash.log"}; rerun with --retry-flash to explicitly retry the saved images.') from None
    else:
        receipt['flash_started'] = True
        save()
        progress('Installing the prepared base…')
        run_tool([*command, 'write_flash', *receipt['flash_args'], *images], session / 'flash.log', timeout=600)
    receipt['flashed'] = True
    save()


def wifi_secret(args):
    from micros_tooling.communication.wifi import credentials_from_terminal, prompt_network_name
    if args.ssid is None:
        require(interactive(args), 'Supply --ssid and --password-file (or --open-network) to configure Wi-Fi without a terminal.')
        ssid = prompt_network_name(progress)
    else:
        ssid = args.ssid.encode('utf-8')
    return credentials_from_terminal(ssid, args, progress)


def connect_wifi(board, port, args, receipt, relay, save=lambda: None):
    expected = receipt['base_sha256']
    if board['platform'] in ('esp8266', 'samd21'):
        if board['platform'] == 'samd21':
            from micros_tooling.platforms.samd21.transport import SerialRemote
        else:
            from micros_tooling.platforms.esp8266.transport import SerialRemote
        with Activity('Waiting for the controller to start') as activity, SerialRemote(port) as remote:
            status = remote.status()
            require(status['identity']['device_id'] == board['device_id'] and status['base_sha256'] == expected, 'USB base identity differs from the prepared board.')
            origin = urlsplit(json.loads((relay / 'server.json').read_text())['url'])
            token = (relay / 'relay.token').read_text().strip()
            # A confirmed provisioning step is not repeated after a later read timeout.
            # The USB identity above is checked again on every resume.
            if not receipt.get('relay_provisioned') or not status['network'].get('relay_configured'):
                try:
                    activity.label = 'Configuring console access'
                    response = remote.request(f'RELAY_SET {origin.hostname} {origin.port or 443} {token}', allow_error=True)
                    require(response.get('result') == 0, 'Console provisioning was rejected.')
                except (OSError, ValueError):
                    raise PackageError('Console provisioning did not confirm; rerun enroll to inspect and resume.') from None
                receipt['relay_provisioned'] = True
                save()
            activity.label = 'Checking saved Wi-Fi (up to 30s)'
            deadline = time.monotonic() + 30
            while (not args.ssid and status['network'].get('configured', True)
                   and not status['network']['connected'] and time.monotonic() < deadline):
                time.sleep(1)
                status = remote.status()
            if args.ssid or not status['network']['connected']:
                with activity.paused():
                    ssid, password = wifi_secret(args)
                activity.label = 'Saving Wi-Fi settings'
                try:
                    response = remote.request('WIFI_SET ' + ssid.hex() + ' ' + (password.hex() or '-'), allow_error=True)
                    require(response.get('result') == 0, 'Wi-Fi settings were rejected.')
                except (OSError, ValueError):
                    raise PackageError('Wi-Fi provisioning did not confirm; rerun enroll to inspect saved settings.') from None
                finally:
                    password = b''
            activity.label = 'Waiting for Wi-Fi connection (up to 90s)'
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                status = remote.status()
                if status['network']['connected']:
                    return
                time.sleep(1)
            raise PackageError('Wi-Fi did not connect. Check the 2.4 GHz network/password and rerun enroll; firmware will not be reflashed.')
    else:
        from micros_tooling.communication.wifi import Wifi, setup_from_terminal
        with Activity('Waiting for the controller to start'):
            wifi = Wifi(port)
        try:
            with Activity('Waiting for Wi-Fi connection (up to 90s)'):
                status = wifi.settled_status(timeout=90)
            require(status['mac'].lower().replace(':', '') == board['device_id'], 'USB board identity changed before Wi-Fi setup.')
            if args.ssid or status['state'] != 'connected':
                setup_from_terminal(wifi, args, progress)
            wifi.device.command('RESUME', 'RESUMED')
        finally:
            wifi.close()


def verify_console(remote, board, expected, timeout=90):
    from micros_tooling.communication.remote import RemoteRejected
    deadline = time.monotonic() + timeout
    delay = 2
    last_error = None
    while True:
        try:
            with Activity('Waiting for console confirmation'):
                roster = json.loads(remote.raw('GET', '/v1/devices'))['devices']
                device = next((d for d in roster if d['device_id'] == board['device_id'] and d['online']), None)
                if device:
                    # Both platforms implement this read-only route. Do not tunnel a
                    # STATUS command through the mutation/opaque platform-command route.
                    status = remote.status()
                    identity = status['identity']
                    require(identity['device_id'] == board['device_id'] and identity['base_sha256'] == expected,
                            'Console answered with a different board or base identity; enrollment is not confirmed.')
                    return status
        except RemoteRejected as error:
            if error.status not in (502, 503, 504):
                raise
            last_error = f'HTTP {error.status}'
        except (TimeoutError, ConnectionError, http.client.HTTPException):
            last_error = 'connection timeout or interruption'
        remaining = deadline - time.monotonic()
        require(remaining > 0,
                'Wi-Fi is configured but the console has not confirmed this board'
                + (f' ({last_error})' if last_error else '')
                + '. Rerun micros enroll to resume verification; the saved firmware and confirmed console provisioning will not be repeated.')
        progress('Waiting for the console' + (f' ({last_error}); retrying the read-only check…' if last_error else ' to see the board…'))
        with Activity('Waiting to retry the console connection'):
            time.sleep(min(delay, remaining))
        delay = min(delay * 2, 8)


def installed_base(board, port, remote, existing):
    """Reuse a known enrollment only when its physically selected base agrees."""
    if not existing:
        return None
    expected = (existing.get('status') or {}).get('identity', {}).get('base_sha256')
    if not expected:
        return None
    try:
        if board['platform'] == 'esp8266':
            from micros_tooling.platforms.esp8266.transport import SerialRemote
            with SerialRemote(port) as serial:
                status = serial.status()
        elif existing.get('online'):
            status = remote.status()
        else:
            return None
    except (OSError, ValueError):
        return None
    identity = status.get('identity', {})
    if identity.get('device_id') == board['device_id'] and identity.get('base_sha256') == expected:
        return expected
    return None


class EnrollmentCancelled(KeyboardInterrupt):
    pass


def cancel_enrollment(remote, board, receipt, save):
    if not receipt.get('pending_enrollment') or receipt.get('confirmed'):
        return 'Enrollment canceled.'
    try:
        with Activity('Removing unfinished enrollment from the dashboard'):
            remote.raw('POST', '/v1/revoke', json.dumps(dict(device_id=board['device_id'])).encode())
            roster = json.loads(remote.raw('GET', '/v1/devices'))['devices']
            require(not any(d['device_id'] == board['device_id'] for d in roster),
                    'Enrollment still appears in the dashboard.')
        receipt['canceled'] = True
        save()
    except (Exception, KeyboardInterrupt):
        return ('Enrollment canceled. Dashboard removal could not be confirmed; '
                'the unfinished enrollment may still be visible. '
                f'Run micros server revoke {board["device_id"]} to remove it.')
    return 'Enrollment canceled. Removed from the dashboard.'


def resume_hint(operator, port, receipt):
    import shlex
    command = shlex.join(['env', 'MICROS_CLIENT_DIR=' + str(operator),
                          'micros', 'enroll', receipt['name'], '--port', port])
    stage = ('Firmware is installed; resuming will keep it.' if receipt.get('flashed') else
             'The flash outcome will be checked before another write.' if receipt.get('flash_started') else
             'Saved preparation will be reused.')
    return stage + '\nResume: ' + command


def enroll(args):
    from micros_tooling.deployment.server_selection import enrollment_server
    require(not getattr(args, 'rebuild_base', False) or not (args.firmware or args.retry_flash or args.detect),
            'Use --rebuild-base without --firmware, --retry-flash or --detect.')
    with enrollment_server(args):
        result = _enroll(args)
        if result.get('online'):
            from micros_tooling.storage.client import application_root
            root = application_root()
            if root:
                from micros_tooling.config.scaffold import bind_starter
                unit = None
                try:
                    unit = bind_starter(root, result['device_id'], result['platform'], result.get('flash_mb'))
                except (OSError, ValueError) as error:
                    progress(f'Board enrollment succeeded; project setup needs attention: {error}')
                if unit:
                    result['project_unit'] = str(unit)
                    result['next_steps'] = [f'micros deploy -d {result["device_id"]} --dry-run',
                                            f'micros deploy -d {result["device_id"]}']
                    result['message'] += f'\nProject unit: {unit.name}\nNext: ' + result['next_steps'][0]
                else:
                    result['message'] += f'\nAdd or update units/{result["device_id"]}.toml for this board before deploying. Existing project settings were preserved.'
        return result


def _enroll(args):
    from micros_tooling.storage.client import operator_directory
    from micros_tooling.fleet.server import configured_remote
    workspace = Workspace(Path(os.environ.get('MICROS_STATE_DIR', ROOT / '.micros')))
    operator = workspace.root if args.detect else operator_directory(workspace).resolve()
    remote = None if args.detect else configured_remote(workspace)
    require(remote is not None or args.detect, 'Configure console operator access first (micros server import-client PATH), then rerun enroll.')
    try:
        roster = [] if args.detect else json.loads(remote.raw('GET', '/v1/devices'))['devices']
    except (ConnectionRefusedError, TimeoutError) as error:
        from micros_tooling.storage.client import server_description
        import shlex
        url = server_description(operator)['url']
        if (operator / 'prvtkey.pem').is_file():
            recovery = 'Start the selected server with ' + shlex.join(['micros', 'server', '--state', str(operator), 'start']) + ', then rerun enroll.'
        else:
            recovery = 'Check its address, network access, and that the server is running on its host, then rerun enroll.'
        raise PackageError(f'No server answered at {url}. {recovery} No controller was accessed.') from error
    port = choose_port(args, roster=None if args.detect else roster)
    from micros_tooling.deployment.samd_enrollment import is_mkr, enroll_mkr
    if is_mkr(port):
        require(not getattr(args, 'rebuild_base', False), '--rebuild-base currently supports ESP8266 enrollment only.')
        return enroll_mkr(args, port, operator, workspace, remote, roster)
    board = probe(port)
    require(not getattr(args, 'rebuild_base', False) or board['platform'] == 'esp8266',
            '--rebuild-base currently supports ESP8266 enrollment only.')
    progress(f'Detected {board["chip"]}, {board["flash_mb"]} MiB flash, ID {board["device_id"]}.')
    if args.detect:
        return dict(**board, port=port, message=f'{board["chip"]} · {board["flash_mb"]} MiB · {board["device_id"]} · {port}')
    existing = next((d for d in roster if d['device_id'] == board['device_id']), None)
    remote = configured_remote(workspace, board['device_id'])
    session = operator / 'onboarding' / board['device_id']
    state = Workspace(session)
    with state.locked():
        receipt = state.read('enrollment.json', {})
        if receipt:
            check_identity(receipt['board'], board)
        if existing:
            require(resumable(receipt, existing) and not getattr(args, 'rebuild_base', False),
                    'This controller is already enrolled. Use micros status or micros deploy for the existing board; '
                    'enrollment will not replace its firmware.')
            progress('Resuming the saved enrollment; keeping the installed firmware and checking its connection.')
        if getattr(args, 'rebuild_base', False):
            require(receipt and not receipt.get('confirmed'),
                    '--rebuild-base requires an unfinished enrollment; confirmed controllers must use the normal update workflow.')
            previous = receipt
            attempt = secrets.token_hex(8)
            state.write(Path('enrollment-history') / (attempt + '.json'), previous)
            receipt = dict(name=previous.get('name'),
                           work_session=str(session / 'rebuilds' / attempt))
            progress('Preserved the previous enrollment attempt; preparing a new base from this SDK.')
        # An erased controller needs fresh installation artifacts. Keep the
        # previous enrollment's paths intact for historical recovery.
        if not receipt and state.read('erase.json', {}).get('console_removed'):
            receipt = dict(work_session=str(session / 'reenrollments' / secrets.token_hex(8)))
        session = Path(receipt.get('work_session', session))
        name = existing['name'] if existing else receipt.get('name') or args.name
        require(not args.name or not name or args.name == name, f'Existing enrollment name is {name!r}; this command will not rename or reset it.')
        if not name:
            require(interactive(args), 'Supply a board name: micros enroll NAME …')
            from micros_tooling.deployment.server_selection import prompt
            name = prompt('Board name', lambda value: valid_board_name(value, roster, board['device_id']))
        valid_board_name(name, roster, board['device_id'])
        if not receipt and not args.firmware and not args.retry_flash:
            installed = installed_base(board, port, remote, existing)
            if installed:
                receipt.update(base_sha256=installed, flashed=True, reused_base=True)
                progress('The installed micros base matches this enrollment; keeping it and checking its connection.')
        if args.firmware and receipt.get('firmware'):
            require(digest(args.firmware.read_bytes()) == receipt['base_sha256'], 'This session already prepared a different base; restore its exact artifacts to resume.')
        pending = not existing or bool(receipt and not receipt.get('confirmed') and not receipt.get('reused_base'))
        receipt.update(board=board, name=name, pending_enrollment=pending)
        def save():
            state.write('enrollment.json', receipt)
        save()
        try:
            relay = credentials(operator, workspace, remote, board, name, roster, args.relay_credentials)
            if not receipt.get('files') and not receipt.get('flashed'):
                progress('Preparing a management-only base…')
                receipt.update(prepare(board, args, session, relay, remote))
                save()
            if not receipt.get('flashed'):
                install(board, port, session, receipt, save, retry=args.retry_flash)
            progress('Connecting Wi-Fi and the console…')
            connect_wifi(board, port, args, receipt, relay, save)
            verify_console(remote, board, receipt['base_sha256'])
            receipt['confirmed'] = True
            receipt['pending_enrollment'] = False
            receipt.pop('canceled', None)
            save()
            return dict(device_id=board['device_id'], name=name, platform=board['platform'], flash_mb=board['flash_mb'], base_sha256=receipt['base_sha256'],
                        online=True, session=str(session), message=f'{name} is online in the console. Base firmware and authenticated connection verified. No application services were deployed.')
        except KeyboardInterrupt:
            raise EnrollmentCancelled(cancel_enrollment(remote, board, receipt, save)
                                      + '\n' + resume_hint(operator, port, receipt)) from None
        except Exception:
            if receipt.get('pending_enrollment') and not receipt.get('confirmed'):
                result = cancel_enrollment(remote, board, receipt, save)
                if 'could not be confirmed' in result:
                    progress(result.replace('Enrollment canceled.', 'Enrollment failed.', 1))
            progress(resume_hint(operator, port, receipt))
            raise
