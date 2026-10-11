from micros_tooling.platforms.registry import supports_identity
"""Discover controllers through micros status, then ESP ROM identification."""
import json
import re
import time

from micros_tooling.storage.packages import require


def ports():
    from serial.tools import list_ports
    grouped = {}
    for p in sorted(list_ports.comports(), key=lambda p: ('SLAB' in p.device, '/tty.' in p.device, p.device)):
        if p.vid is None:
            continue
        # Serial numbers are not unique on many inexpensive USB bridges.
        key = (p.vid, p.pid, p.location) if p.location else p.device
        if key not in grouped:
            grouped[key] = dict(port=p.device, adapter=p.description, aliases=[], vid=p.vid, pid=p.pid)
        grouped[key]['aliases'].append(p.device)
    return list(grouped.values())


def identity(value):
    if not isinstance(value, str):
        return None
    value = value.lower().replace(':', '')
    return value if re.fullmatch(r'[0-9a-f]{12}', value) else None


def probe(candidate, timeout=5):
    import serial
    result = dict(candidate, state='unidentified', reason='No micros identity reply')
    connection = serial.Serial(port=None, baudrate=115200, timeout=.1, write_timeout=.3, exclusive=True)
    # Do not deliberately reset into the bootloader or toggle control lines.
    connection.dtr = False
    connection.rts = False
    connection.port = candidate['port']
    try:
        connection.open()
        deadline = time.monotonic() + timeout
        next_request = 0
        buffer = bytearray()
        total = 0
        while time.monotonic() < deadline and total < 65536:
            now = time.monotonic()
            if now >= next_request:
                connection.write(b'RPC 0 0 0 0 - -\n')
                next_request = now + 1
            chunk = connection.read(512)
            total += len(chunk)
            buffer.extend(chunk)
            while b'\n' in buffer:
                raw, _, rest = buffer.partition(b'\n')
                buffer = bytearray(rest)
                if len(raw) > 8192:
                    continue
                try:
                    line = raw.decode('utf-8').strip()
                except UnicodeError:
                    continue
                try:
                    value = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if not isinstance(value, dict):
                    continue
                platform = value.get('platform')
                detail = value.get('identity')
                device_id = identity(detail.get('device_id')) if isinstance(detail, dict) else None
                if value.get('result') != 0 or not supports_identity(platform, value.get('target')):
                    continue
                if device_id:
                    result.update(state='identified', platform=platform, device_id=device_id)
                    result.pop('reason')
                    return result
            if len(buffer) > 8192:
                # Discard an overlong frame through its newline, never parse its tail.
                while b'\n' not in buffer and time.monotonic() < deadline and total < 65536:
                    chunk = connection.read(512)
                    total += len(chunk)
                    buffer.extend(chunk)
                buffer = bytearray(buffer.partition(b'\n')[2])
        return result
    except (serial.SerialException, OSError):
        result.update(state='unavailable', reason='Port is busy, disconnected, or inaccessible')
        return result
    finally:
        connection.close()


def probe_controller(candidate, timeout=5):
    result = probe(candidate, timeout)
    if result['state'] != 'unidentified':
        return result
    if candidate.get('vid') in (0x2341, 0x2a03):
        if candidate.get('pid') in (0x8054, 0x0054):
            return dict(candidate, state='identified', chip='SAMD21G18A (MKR WiFi 1010 USB identity)',
                        platform='samd21', source='usb', supported=True)
        return dict(result, supported=False, reason='Arduino USB interface; board model not supported yet')
    if candidate.get('vid') is not None and candidate['vid'] not in (0x303A, 0x10C4, 0x1A86, 0x0403):
        return dict(result, supported=False, reason='USB device recognized; chip not identified, enrollment not supported yet')
    from micros_tooling.deployment import enrollment as e
    from micros_tooling.storage.packages import PackageError
    try:
        board = e.parse_probe(e.run_tool([*e.esptool(), '--port', candidate['port'], 'flash_id'], timeout=30), enforce_support=False)
    except (PackageError, OSError, ValueError):
        return dict(result, reason='No supported chip identified by USB/ROM probe')
    supported = (board['platform'] == 'esp8266' and board['flash_mb'] == 4 or
                 board['platform'] == 'esp32' and board['flash_mb'] in (4, 8))
    return dict(candidate, **board, state='identified', source='rom', supported=supported)


def discover(port=None, timeout=5):
    from concurrent.futures import ThreadPoolExecutor
    candidates = [dict(port=port, adapter='Selected serial interface', aliases=[port])] if port else ports()
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(lambda p: probe_controller(p, timeout), candidates))


# Operations must be added together with their platform implementation/tests.
OPERATIONS = {'esp8266': {'enroll', 'erase'}, 'esp32': {'enroll', 'erase'},
              'samd21': {'enroll', 'erase'}}


def operation_blocker(result, operation):
    if result.get('supported') is False:
        return f'{operation} not supported yet'
    platform = result.get('platform')
    if platform and operation not in OPERATIONS.get(platform, set()):
        return f'{operation} not supported yet'
    if platform == 'samd21':
        if result.get('vid') is not None and (result['vid'] not in (0x2341, 0x2a03) or result.get('pid') not in (0x8054, 0x0054)):
            return f'{operation} not supported yet for this SAMD21 board'
        if operation == 'erase' and not result.get('device_id'):
            return 'erase unavailable: console identity requires running micros'
    if result.get('state') == 'unavailable':
        return f'{operation} unavailable: interface is busy or disconnected'
    return None


def describe(result, operation=None):
    if result['state'] == 'identified':
        label = result.get('chip', result['platform'].upper())
        source = {'rom': 'ROM detected', 'usb': 'USB identified'}.get(result.get('source'), 'micros')
        if operation:
            blocker = operation_blocker(result, operation)
            support = ' · ' + (blocker or f'{operation} supported')
        else:
            support = ' · not supported yet' if result.get('supported') is False or result.get('platform') not in OPERATIONS else ' · supported'
        return f"{label} · {result.get('device_id') or 'identity pending'} · {source}{support}"
    return f"{result['state']} — {result['reason']}"


def add_parser(commands):
    parser = commands.add_parser('discover', help='identify micros controllers on USB serial interfaces')
    parser.add_argument('--port', help='probe only this serial interface')
    parser.add_argument('--timeout', type=float, default=5, help='seconds per interface (default: 5; maximum: 30)')
    parser.add_argument('--json', action='store_true')


def run(args):
    require(0 < args.timeout <= 30, '--timeout must be greater than zero and at most 30 seconds.')
    from micros_tooling.terminal.progress import message, Activity
    message('Discovering controllers; ROM probing resets interfaces that do not respond to micros.')
    with Activity('Identifying connected controllers'):
        results = discover(args.port, args.timeout)
    if args.json:
        print(json.dumps(results, indent=2))
    elif not results:
        print('No USB serial interfaces found.')
    else:
        for result in results:
            print(f"{result['port']}: {describe(result)}")
