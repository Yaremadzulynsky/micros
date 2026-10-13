"""MKR implementation of the normal micros development commands."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from micros_tooling.storage.packages import require
from micros_tooling.storage.store import atomic_write
from micros_tooling.platforms.samd21.build import ROOT, base_info, build
from micros_tooling.platforms.samd21.transport import SerialRemote, find_port


def state_root():
    return Path(os.environ.get('MICROS_STATE_DIR', ROOT / '.micros')) / 'samd21'


def profile_path(name):
    require(isinstance(name, str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', name), 'Invalid MKR device name')
    return state_root() / 'devices' / (name + '.json')


def handles(args):
    if getattr(args, 'platform', None) == 'samd21':
        return True
    name = getattr(args, 'device', None)
    return bool(name and re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', name) and profile_path(name).is_file())


def emit(value, args):
    if getattr(args, 'json', False):
        print(json.dumps(value))
    elif isinstance(value, str):
        print(value)
    else:
        print(json.dumps(value, indent=2))


def wait_confirmed(remote, bank):
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        status = remote.status()
        if not status['pending']:
            require(status['good'] == bank and status['active'] == bank, 'Application failed; known-good fallback selected')
            return status
        time.sleep(.15)
    raise TimeoutError('Application trial still pending; inspect status')


def wait_running(remote):
    deadline = time.monotonic() + 5
    while True:
        status = remote.status()
        if status['services'] and all(s['state'] in (4, 'Running') for s in status['services']):
            return status
        require(time.monotonic() < deadline, 'Services did not become running; inspect status and logs')
        time.sleep(.1)


def connect(args, profile, port):
    if (getattr(args, 'via', None) or 'usb') == 'usb':
        from micros_tooling.platforms.embedded.transport import verify_selected_usb
        return verify_selected_usb(SerialRemote(port, profile.get('serial_number')), profile.get('device_id'))
    from micros_tooling.fleet.server import configured_remote
    from micros_tooling.storage.workspace import Workspace
    from micros_tooling.platforms.samd21.transport import NetworkRemote
    require(profile.get('device_id'), 'Select an enrolled controller with -d NAME.')
    relay = configured_remote(Workspace(state_root().parent), profile['device_id'])
    require(relay is not None, 'Configure console operator access first.')
    return NetworkRemote(relay)


def main(args):
    require(not getattr(args, 'to', None), 'MKR rollback selects the previous confirmed bank; deploy a release directory for a specific version')
    require(not getattr(args, 'environment', None), 'Use --overlay for MKR service configuration')
    name = getattr(args, 'name', None) if args.command == 'init' else getattr(args, 'device', None)
    profile = json.loads(profile_path(name).read_text()) if name and profile_path(name).is_file() else {}
    profile.update(getattr(args, 'enrolled_profile', {}))
    firmware = Path(getattr(args, 'firmware', None) or (ROOT / 'build/samd21/firmware/runtime.ino.elf' if args.command == 'init' else profile.get('firmware', ROOT / 'build/samd21/firmware/runtime.ino.elf')))
    compiler = Path(getattr(args, 'compiler_dir', None) or profile.get('compiler_dir', '/opt/gcc-arm-none-eabi-10-2020-q4-major/bin'))
    board = Path(getattr(args, 'board', None) or profile.get('board', ROOT / 'examples/mkr-demo/board.toml'))
    project = getattr(args, 'project', None)
    if project is None or project == ROOT / 'config/micros.toml':
        project = Path(profile.get('project', ROOT / 'examples/hello-service/micros.toml'))
    from micros_tooling.config.configuration import read_toml
    if not getattr(args, 'board', None) and 'board' in read_toml(project):
        board = Path(project)
    port = getattr(args, 'port', None)
    if args.command == 'init':
        if args.phase == 'plan':
            emit(dict(platform='samd21', board=str(board), project=str(project), compiler=str(compiler),
                      next='Use --phase prepare, then --phase flash, or --phase connect for an already flashed MKR'), args)
            return
        if args.phase == 'prepare':
            from micros_tooling.deployment.samd_enrollment import prepare_tools
            compiler = prepare_tools(ROOT / 'build/samd21', getattr(args, 'compiler_dir', None))
            subprocess.run([sys.executable, str(ROOT / 'src/micros_tooling/platforms/build_samd21.py'), '--compiler-dir', str(compiler)], check=True)
            emit(dict(firmware=str(firmware), phase='prepared'), args)
            return
        info = base_info(firmware)
        if args.phase == 'flash':
            from micros_tooling.platforms.samd21.flash import flash
            port = flash(firmware, port, profile.get('serial_number'))
        with SerialRemote(port, profile.get('serial_number')) as remote:
            status = remote.status()
            require(status['base_sha256'] == info['hash'].hex(), 'Connected base differs from selected ELF')
            device_id = status['identity']['device_id']
            deadline = time.monotonic() + 5
            while device_id == '000000000000' and time.monotonic() < deadline:
                time.sleep(.2)
                status = remote.status()
                device_id = status['identity']['device_id']
            require(re.fullmatch('[0-9a-f]{12}', device_id) and device_id != '000000000000',
                    'MKR Wi-Fi identity is not ready; inspect status before pairing.')
            credentials = getattr(args, 'relay_credentials', None)
            if credentials:
                from urllib.parse import urlsplit
                require(credentials.name == device_id, 'Enrollment identity does not match this MKR')
                origin = urlsplit(json.loads((credentials / 'server.json').read_text())['url'])
                require(origin.scheme == 'https' and origin.hostname and origin.path in ('', '/')
                        and not origin.username and not origin.query and not origin.fragment, 'Invalid relay HTTPS origin')
                token = (credentials / 'relay.token').read_text().strip()
                require(re.fullmatch('[0-9a-f]{64}', token), 'Invalid relay device token')
                remote.request(f'RELAY_SET {origin.hostname} {origin.port or 443} {token}')
            import shutil
            base_directory = state_root() / 'bases' / status['base_sha256']
            base_directory.mkdir(parents=True, exist_ok=True)
            saved_firmware = base_directory / 'runtime.ino.elf'
            if firmware.resolve() != saved_firmware.resolve():
                shutil.copyfile(firmware, saved_firmware)
                binary = firmware.with_suffix('.bin')
                if binary.is_file(): shutil.copyfile(binary, saved_firmware.with_suffix('.bin'))
            profile = dict(platform='samd21', device_id=device_id, serial_number=remote.serial_number, firmware=str(saved_firmware.resolve()),
                           compiler_dir=str(compiler.resolve()), board=str(board.resolve()), project=str(Path(project).resolve()))
        path = profile_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, json.dumps(profile, indent=2).encode() + b'\n')
        emit(dict(device=name, paired=True, status=status), args)
        return
    if args.command == 'base-update':
        from micros_tooling.platforms.samd21.base_ota import update
        with connect(args,profile,port) as remote:
            result=update(remote,firmware,getattr(args,'image',None),getattr(args,'dry_run',False))
        if result.get('confirmed'):
            import shutil
            directory=state_root()/'bases'/result['status']['base_sha256']
            directory.mkdir(parents=True,exist_ok=True)
            saved=directory/'runtime.ino.elf'
            if firmware.resolve()!=saved.resolve():shutil.copyfile(firmware,saved)
            profile['firmware']=str(saved.resolve())
            binary=Path(firmware).with_suffix('.bin')
            if binary.is_file() and binary.resolve() != saved.with_suffix('.bin').resolve():
                shutil.copyfile(binary,saved.with_suffix('.bin'))
            from micros_tooling.deployment.selection import record_base_update
            record_base_update(args,result,saved)
            atomic_write(profile_path(name),json.dumps(profile,indent=2).encode()+b'\n')
        emit(result,args);return
    if args.command in ('config', 'generate'):
        from micros_tooling.config.configuration import load_project, generate_service_headers
        emit(generate_service_headers(project, board) if args.command == 'generate' else load_project(project, getattr(args, 'overlay', None), board), args)
        return
    if args.command == 'history':
        path = state_root() / 'history' / ((name or 'usb') + '.json')
        emit(json.loads(path.read_text()) if path.exists() else [], args)
        return
    require(args.command in ('build', 'deploy', 'status', 'logs', 'stop', 'recover', 'reboot', 'rollback', 'doctor', 'wifi'), 'Command is not implemented for SAMD21')
    offline = args.command == 'build' and getattr(args, 'bank', None) is not None
    if offline:
        output = Path(getattr(args, 'bundle', None) or getattr(args, 'output', None) or state_root() / 'build' / (name or 'usb'))
        report = build(project, firmware, output, compiler, args.bank, board, getattr(args, 'overlay', None))
        emit(dict(output=str(output), **report), args)
        return
    with connect(args, profile, port) as remote:
        status = remote.status()
        if args.command in ('status', 'doctor'):
            if args.command == 'doctor':
                status['paired_base_matches'] = firmware.is_file() and status['base_sha256'] == base_info(firmware)['hash'].hex()
                status['serial_number'] = remote.serial_number
            emit(status, args)
        elif args.command == 'logs':
            while True:
                result = remote.request('LOGS')
                text = bytes.fromhex(result['hex']).decode('utf-8', errors='replace')
                if args.json: print(json.dumps(dict(text=text)))
                else: print(text, end='', flush=True)
                if not getattr(args, 'follow', False): break
                time.sleep(.3)
        elif args.command in ('stop', 'recover', 'reboot', 'rollback'):
            expected = status['previous'] if args.command == 'rollback' else None
            if args.command == 'rollback' and getattr(args, 'dry_run', False):
                require(expected in (0, 1), 'No previous bank is available')
                emit(dict(previous=expected, dry_run=True), args)
                return
            result = remote.request(args.command.upper())
            if expected is not None: result = wait_confirmed(remote, expected)
            if args.command == 'recover': result = wait_running(remote)
            emit(result, args)
        elif args.command in ('build', 'deploy'):
            output = Path(getattr(args, 'bundle', None) or getattr(args, 'output', None) or state_root() / 'build' / (name or 'usb'))
            release = getattr(args, 'release', None)
            if release:
                output = Path(release)
                report = json.loads((output / 'report.json').read_text())
                require(report['base_sha256'] == status['base_sha256'], 'Release was built for a different base')
            else:
                require(status['base_sha256'] == base_info(firmware)['hash'].hex(), 'Base changed; pair the exact ELF with init --phase connect')
                if args.command == 'deploy' and not getattr(args, 'force', False) and status['good'] in (0, 1) and not status['pending'] and status['active'] == status['good']:
                    current = build(project, firmware, output / 'current-check', compiler, status['good'], board, getattr(args, 'overlay', None))
                    if current['graph_sha256'] == status['good_sha256'] and all(s['state'] in (4, 'Running') for s in status['services']):
                        from micros_tooling.platforms.embedded.releases import publish
                        from micros_tooling.storage.workspace import Workspace
                        publish(Workspace(state_root().parent), remote, status, current)
                        emit(dict(unchanged=True, message='Application already matches; no flash writes or restart.', status=status), args)
                        return
                bank = 1 - status['good'] if status['good'] < 2 else 0
                require(getattr(args, 'bank', None) in (None, bank), 'Requested bank is not inactive')
                report = build(project, firmware, output, compiler, bank, board, getattr(args, 'overlay', None))
            if args.command == 'build' or getattr(args, 'dry_run', False):
                emit(dict(output=str(output), **report), args)
                return
            result = remote.deploy((output / 'bank.bin').read_bytes(), report)
            from micros_tooling.platforms.embedded.releases import publish
            from micros_tooling.storage.workspace import Workspace
            publish(Workspace(state_root().parent), remote, result, report)
            path = state_root() / 'history' / ((name or 'usb') + '.json')
            history = json.loads(path.read_text()) if path.exists() else []
            history.append(dict(time=time.time(), report=report, status=result))
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(path, json.dumps(history, indent=2).encode() + b'\n')
            emit(result, args)
        elif args.command == 'wifi':
            if args.wifi_action in ('status', 'list'):
                emit(remote.request('WIFI_GET' if args.wifi_action=='list' else 'WIFI'), args)
            elif args.wifi_action in ('setup', 'add'):
                import getpass
                ssid = args.ssid or input('Network name: ')
                password = '' if args.open_network else (args.password_file.read_text().rstrip('\n')
                    if args.password_file else getpass.getpass('Wi-Fi password: '))
                ssid, password = ssid.encode('utf-8'), password.encode('utf-8')
                require(0 < len(ssid) <= 32 and len(password) <= 64 and b'\0' not in ssid + password,
                        'Invalid network name or password length')
                from server.wifi import encode
                encode(dict(networks=[dict(ssid=ssid.decode('utf-8'),password=password.decode('utf-8')),None,None,None]))
                if args.wifi_action=='add' or getattr(args,'fallback',False):
                    current=remote.request('WIFI_GET')['networks']
                    primary=next((n for n in current if not n.get('fallback')),None)
                    require(primary,'Set up the primary Wi-Fi network first')
                    require(remote.request('WIFI').get('profiles_capacity',1)>=2,'Install the two-network MKR base first')
                    remote.request('WIFI_PROFILES '+primary['ssid_hex']+' keep '+ssid.hex()+' '+(password.hex() or '-'))
                    emit(remote.request('WIFI_GET'),args);return
                remote.request('WIFI_SET ' + ssid.hex() + ' ' + (password.hex() or '-'))
                deadline = time.monotonic() + 20
                while True:
                    result = remote.request('WIFI')
                    if result['connected'] or time.monotonic() >= deadline:
                        break
                    time.sleep(.5)
                emit(result, args)
            else:
                raise ValueError('MKR supports wifi setup, add, status and list; select an SSID explicitly')
