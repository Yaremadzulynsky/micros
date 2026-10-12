"""Remove a USB controller from management, then erase firmware and settings."""
import json
import os
import secrets
from contextlib import ExitStack
from pathlib import Path

from micros_tooling.deployment import enrollment as e
from micros_tooling.storage.packages import require
from micros_tooling.storage.workspace import Workspace


def add_parser(commands):
    parser = commands.add_parser('erase', help='remove a controller from the console and erase its firmware and settings')
    parser.add_argument('--port', help='USB serial interface; otherwise choose a connected controller')
    parser.add_argument('--yes', action='store_true', help='confirm destruction without a prompt; requires --port')
    parser.add_argument('--json', action='store_true', help='machine-readable result; requires --yes and --port')


def flash_command(board, port):
    return [*e.esptool(), '--chip', board['platform'], '--port', port, '--baud', '115200', '--after', 'no_reset']


def invalidate_enrollment(state, session):
    previous = state.read('enrollment.json', {})
    if previous:
        Workspace(session).write('previous-enrollment.json', previous)
        # Keep the previous artifacts and receipt, but never reuse its flashed flag.
        state.write('enrollment.json', {})


def erase(args):
    require(not args.yes or args.port, '--yes requires an explicit --port for erasure.')
    port = e.choose_port(args)
    from micros_tooling.deployment.samd_enrollment import is_mkr, read_identity
    mkr = is_mkr(port)
    device = None
    if mkr:
        from micros_tooling.platforms.samd21 import flash as samd_flash
        device = samd_flash.select_device(port)
        require(device.pid == 0x8054, 'SAMD21 erase requires running micros to verify its console identity; restart into micros first.')
        samd_flash.erase_programmer()  # Check tools before changing the console.
    def identify():
        if not mkr:
            return e.probe(port)
        with e.Activity('Identifying SAMD21 controller'):
            current = samd_flash.select_device(port, device.serial_number)
            require(current.location == device.location, 'The selected USB controller changed.')
            device_id, _ = read_identity(port)
        return dict(platform='samd21', chip='SAMD21G18A', device_id=device_id, flash_mb=.25)
    board = identify()
    e.progress(f'Detected {board["chip"]}, {board["flash_mb"]} MiB flash, ID {board["device_id"]}.')
    from micros_tooling.storage.client import operator_directory
    from micros_tooling.fleet.server import configured_remote
    workspace = Workspace(Path(os.environ.get('MICROS_STATE_DIR', e.ROOT / '.micros')))
    operator = operator_directory(workspace).resolve()
    remote = configured_remote(workspace, board['device_id'])
    require(remote is not None, 'Configure console operator access before erasing so enrollment removal can be verified.')
    roster = json.loads(remote.raw('GET', '/v1/devices'))['devices']
    existing = next((d for d in roster if d['device_id'] == board['device_id']), None)
    name = existing['name'] if existing else board['device_id']
    e.progress(f'Erase {name}: firmware, applications, Wi-Fi and board credentials will be cleared; no flash backup will be made. Console history will be retained.')
    if mkr:
        e.progress('The Arduino USB bootloader is retained for re-enrollment.')
    if not args.yes:
        require(e.interactive(args), 'Erasure requires confirmation. Use --port PORT --yes without a terminal.')
        answer = input(f'Type {board["device_id"]} to remove this controller from the console and erase its firmware and settings: ').strip()
        require(answer == board['device_id'], 'Erasure cancelled; flash and console enrollment were not changed.')
    state = Workspace(operator / 'onboarding' / board['device_id'])
    # SAMD enrollment is initially keyed by USB location, before its NINA MAC
    # is available. Invalidate every matching receipt, including prior ports.
    states = [state]
    if mkr:
        from micros_tooling.storage.packages import digest
        key = digest((device.location or device.serial_number or port).encode())[:24]
        current = operator / 'onboarding' / ('mkr-usb-' + key)
        roots = set((operator / 'onboarding').glob('mkr-usb-*')) | {current}
        for root in sorted(roots):
            candidate = Workspace(root)
            identity = candidate.read('enrollment.json', {}).get('board', {}).get('device_id')
            if identity == board['device_id'] or (root == current and not identity):
                states.append(candidate)
    with ExitStack() as locks:
        for item in sorted(states, key=lambda item: str(item.root)):
            locks.enter_context(item.locked())
        receipt = state.read('erase.json', {})
        if not receipt or receipt.get('complete') or (receipt.get('erase_started') and state.read('enrollment.json', {})):
            session = state.root / 'erasures' / secrets.token_hex(8)
            receipt = dict(board=board, session=str(session))
        else:
            e.check_identity(receipt['board'], board)
            session = Path(receipt['session'])
        def save():
            state.write('erase.json', receipt)
            Workspace(session).write('erase.json', receipt)
        save()
        if mkr:
            e.check_identity(board, identify())
        # Always recheck the server, including when resuming an interrupted erase.
        with e.Activity('Removing controller from the console'):
            remote.raw('POST', '/v1/revoke', json.dumps(dict(device_id=board['device_id'])).encode())
            roster = json.loads(remote.raw('GET', '/v1/devices'))['devices']
        require(not any(d['device_id'] == board['device_id'] for d in roster),
                'The controller remains enrolled in the console; flash was not erased.')
        receipt['console_removed'] = True
        save()
        for item in states:
            invalidate_enrollment(item, session if item is state else session / item.root.name)
        if mkr:
            e.check_identity(board, identify())
        receipt['erase_started'] = True
        save()
        e.progress('Console removal verified. Erasing firmware and settings…' if mkr else 'Console removal verified. Erasing all flash…')
        if mkr:
            samd_flash.erase(port, device.serial_number, session / 'erase.log')
        else:
            e.run_tool([*flash_command(board, port), 'erase_flash'], session / 'erase.log', timeout=600)
        receipt['complete'] = True
        save()
        return dict(device_id=board['device_id'], platform=board['platform'], erased=True, console_removed=True,
                    session=str(session), message=f'{name}: flash erase completed; removed from the console. Run micros enroll to install firmware again.')
