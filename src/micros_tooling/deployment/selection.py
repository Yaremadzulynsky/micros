"""Resolve enrolled device identity and preserve verified base selections."""

def resolve_enrolled_platform(args):
    """Route a named enrolled controller using its authenticated roster metadata."""
    import json
    import os
    from pathlib import Path
    from micros_tooling.storage.workspace import Workspace
    from micros_tooling.storage.client import operator_directory
    from micros_tooling.fleet.server import configured_remote
    commands = {'status', 'logs', 'doctor', 'build', 'deploy', 'history', 'restart', 'stop', 'recover', 'reboot', 'rollback', 'wifi', 'base-update'}
    if args.command not in commands or getattr(args, 'platform', None) or not getattr(args, 'device', None):
        return
    root = Path(os.environ.get('MICROS_STATE_DIR', Path(__file__).resolve().parents[3] / '.micros'))
    workspace = Workspace(root)
    remote = configured_remote(workspace)
    if remote is None:
        return
    roster = json.loads(remote.raw('GET', '/v1/devices'))['devices']
    selected = [d for d in roster if args.device in (d['name'], d['device_id'])]
    if len(selected) != 1:
        return
    selected = selected[0]
    platform = (selected.get('status') or {}).get('platform')
    if platform not in ('samd21', 'esp8266'):
        return
    args.platform = platform
    if not getattr(args, 'via', None):
        args.via = 'usb' if getattr(args, 'port', None) else 'relay'
    profile = dict(platform=platform, device_id=selected['device_id'])
    # The enrollment receipt already owns the exact prepared base. Reuse it;
    # do not require a second legacy pairing step after successful enrollment.
    operator = operator_directory(workspace)
    for path in sorted((operator / 'onboarding').glob('*/enrollment.json')):
        receipt = json.loads(path.read_text())
        if receipt.get('confirmed') and receipt.get('board', {}).get('device_id') == selected['device_id']:
            if receipt.get('firmware'):
                profile['firmware'] = receipt['firmware']
                firmware = Path(receipt['firmware'])
                if platform == 'esp8266' and not firmware.with_suffix('.bin').exists():
                    # Older enrollment receipts omitted the adjacent BIN, but
                    # retain the exact, hashed application image used to flash.
                    from micros_tooling.storage.packages import require, digest
                    from micros_tooling.storage.store import atomic_write
                    image = next((i for i in receipt.get('files', []) if i['offset'] == 0x10000), None)
                    if image:
                        data = Path(image['path']).read_bytes()
                        require(digest(data) == image['sha256'], 'Saved enrollment image changed.')
                        atomic_write(firmware.with_suffix('.bin'), data)
            break
    args.enrolled_profile = profile



def record_base_update(args, result, firmware):
    """Keep successful enrollment's exact base usable after a verified update."""
    if not result.get('confirmed') or not getattr(args, 'enrolled_profile', None):
        return
    import os
    from pathlib import Path
    from micros_tooling.storage.workspace import Workspace
    from micros_tooling.storage.client import operator_directory
    root = Path(os.environ.get('MICROS_STATE_DIR', Path(__file__).resolve().parents[3] / '.micros'))
    operator = operator_directory(Workspace(root))
    device_id = args.enrolled_profile['device_id']
    for path in sorted((operator / 'onboarding').glob('*/enrollment.json')):
        state = Workspace(path.parent)
        candidate = state.read('enrollment.json', {})
        if not candidate.get('confirmed') or candidate.get('board', {}).get('device_id') != device_id:
            continue
        with state.locked():
            receipt = state.read('enrollment.json', {})
            if receipt.get('confirmed') and receipt.get('board', {}).get('device_id') == device_id:
                receipt.setdefault('previous_bases', []).append(dict(firmware=receipt['firmware'], base_sha256=receipt['base_sha256']))
                receipt.update(firmware=str(Path(firmware).resolve()), base_sha256=result['status']['base_sha256'])
                state.write('enrollment.json', receipt)
                return
