"""Local server setup, enrollment and operator access for the outbound management relay."""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

from micros_tooling.storage.packages import require
from micros_tooling.storage.store import atomic_write
from micros_tooling.communication.remote import Remote, accepted, decode_response, RESPONSE_LIMIT

ROOT = Path(__file__).resolve().parents[3]


class RelayRemote(Remote):
    """Reuse existing status validation and deployment leases over an HTTPS relay."""
    def __init__(self, url, certificate, token_file, device_id, *, cloudflare_access=False):
        import re
        require(not device_id or re.fullmatch('[0-9a-f]{12}', device_id), 'Invalid relay device ID')
        parsed = urlsplit(url)
        require(parsed.scheme == 'https' and parsed.hostname and not parsed.username
                and parsed.path in ('', '/') and not parsed.query and not parsed.fragment,
                'Server URL must be an HTTPS origin, such as https://192.168.0.25:8443')
        super().__init__(parsed.hostname, certificate, token_file, parsed.port or 443)
        self.context.check_hostname = True
        self.device_id = device_id
        self.access_origin = url.rstrip('/') if cloudflare_access else None
        self.access_token = None

    def access_headers(self):
        """Read the user's cached Access login; never put either token in a URL."""
        if not self.access_origin:
            return {}
        if self.access_token is None:
            executable = shutil.which('cloudflared')
            require(executable, 'Install cloudflared to access this protected server.')
            instruction = 'Sign in first: cloudflared access login '+self.access_origin
            try:
                result = subprocess.run([executable, 'access', 'token', '--app', self.access_origin],
                                        capture_output=True, text=True, timeout=15)
            except (OSError, subprocess.TimeoutExpired):
                require(False, instruction)
            import re
            token = result.stdout.strip()
            require(result.returncode == 0 and len(token) < 16384
                    and re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', token), instruction)
            self.access_token = token
        return {'Cf-Access-Token': self.access_token}

    def raw(self, method, path, body=b'', headers=None):
        import http.client
        access_headers = self.access_headers()
        connection = http.client.HTTPSConnection(self.host, self.port, context=self.context, timeout=25)
        try:
            connection.request(method, path, body, {'Authorization': 'Bearer '+self.token,
                **({'X-Micros-Session':self.session_id} if self.session_id else {}), **(headers or {}), **access_headers})
            response = connection.getresponse()
            # The roster contains many bounded device observations; individual replies stay small.
            from micros_tooling.storage.artifacts import LIMIT as ARTIFACT_LIMIT
            limit = ARTIFACT_LIMIT if path.startswith('/v1/artifacts/') else 256 * 1024 if path.startswith('/v1/inspect/') else (1024 * 1024 if path in ('/v1/devices','/v1/coordination') else RESPONSE_LIMIT)
            data = response.read(limit+1)
            if self.access_origin and response.status in (302, 401, 403):
                require(False, 'Access or operator authentication rejected. Renew your login: cloudflared access login '+self.access_origin)
            require(len(data) <= limit, 'Oversized relay response')
            accepted(response.status, data)
            return data
        finally:
            connection.close()

    def register_release(self, inspection):
        """Publish non-secret labels from locally validated package admission."""
        payload=dict(before=dict(identity=dict(base_sha256=inspection['before']['identity']['base_sha256'])),
                     plan=dict(services=[dict(name=s['name'],version=s['version'],permissions=dict(publish_mask=s['permissions']['publish_mask'])) for s in inspection['plan']['services']],
                               channels=[dict(key=c['key'],name=c['name']) for c in inspection['plan']['channels']]),
                     banks={str(bank):dict(digest=value['digest']) for bank,value in inspection['banks'].items()})
        if inspection['plan'].get('channel_ports'):
            payload['plan']['channel_ports'] = inspection['plan']['channel_ports']
        if inspection['plan'].get('service_commands'):
            payload['plan']['service_commands'] = inspection['plan']['service_commands']
        self.raw('POST','/v1/release-labels',json.dumps(payload).encode())

    def request(self, method, path, body=b'', token=None):
        require(token is None, 'Relay requests use the saved operator token')
        payload = self.raw(method, '/devices/'+self.device_id+path, body)
        return payload.decode(errors='replace') if path == '/v1/logs' else decode_response(payload)


def connect_profile(workspace, name, profile):
    relay = profile['relay']
    directory = workspace.root/'devices'/name
    return RelayRemote(relay['url'], directory/'relay-ca.pem', directory/'relay-admin.token', relay['device_id'],
                       cloudflare_access=relay.get('cloudflare_access') is True)


def server_main(arguments):
    parser = argparse.ArgumentParser(prog='micros server', description=__doc__)
    from micros_tooling.storage.client import operator_directory
    from micros_tooling.storage.workspace import Workspace
    parser.add_argument('--compose-project', default=os.environ.get('MICROS_COMPOSE_PROJECT'),
                        help='isolated Docker Compose project for start/shutdown (or MICROS_COMPOSE_PROJECT)')
    location = parser.add_mutually_exclusive_group()
    location.add_argument('--state', type=Path, help='explicit operator/server state directory')
    location.add_argument('--profile', help='named server profile; default selects the original saved server')
    sub = parser.add_subparsers(dest='action', required=True)
    listing = sub.add_parser('list', help='list saved server profiles without connecting')
    listing.add_argument('--json', action='store_true')
    use = sub.add_parser('use', help='select a saved server for this project, or this user outside a project')
    use.add_argument('profile_name')
    client_import = sub.add_parser('import-client', help='copy operator authentication from an existing server directory')
    client_import.add_argument('directory', type=Path)
    setup = sub.add_parser('setup', help='create private TLS/operator credentials for a server hostname or IP')
    setup.add_argument('--host', required=True)
    sub.add_parser('console', help='open the web console with a one-time sign-in link')
    sub.add_parser('start', help='build and start the local Docker container')
    sub.add_parser('shutdown', help='stop the local container without deleting state')
    enrollment = sub.add_parser('enroll', help='authorize an ESP MAC before it connects')
    enrollment.add_argument('device_id')
    enrollment.add_argument('--name', required=True)
    revoke = sub.add_parser('revoke', help='disable a device enrollment without replaying queued work')
    revoke.add_argument('device_id')
    for action in ('devices', 'status', 'logs', 'stop', 'recover', 'reboot'):
        command = sub.add_parser(action)
        if action != 'devices':
            command.add_argument('device_id')
        else:
            command.add_argument('--json', action='store_true')
    publication = sub.add_parser('publish-base', help='store an exact base ELF and adjacent sdkconfig on the server')
    publication.add_argument('--firmware', type=Path, required=True)
    history = sub.add_parser('publish-history', help='archive a paired device’s recorded releases on the server')
    history.add_argument('name')
    binding = sub.add_parser('bind', help='route an already-paired local device through this server')
    binding.add_argument('name')
    binding.add_argument('device_id')
    args = parser.parse_args(arguments)
    from micros_tooling.storage.client import profile_directory, saved_servers, select_server
    workspace = Workspace(Path(os.environ.get('MICROS_STATE_DIR', ROOT / '.micros')))
    if args.action == 'list':
        profiles = saved_servers(workspace)
        if args.json:
            print(json.dumps(profiles, indent=2))
        else:
            for profile in profiles:
                print(profile['name'] + ': ' + profile.get('url', profile.get('error', 'incomplete'))
                      + (' · Cloudflare Access' if profile.get('cloudflare_access') else ''))
            if not profiles:
                print('No saved servers. Use server --profile NAME import-client DIRECTORY or setup --host HOST.')
        return
    if args.action == 'use':
        require(not args.state and not args.profile, 'server use takes a profile name, not --state or --profile.')
        require(not os.environ.get('MICROS_CLIENT_DIR') and not os.environ.get('MICROS_SERVER'),
                'Unset MICROS_CLIENT_DIR and MICROS_SERVER before saving a different default server.')
        directory = select_server(args.profile_name)
        from micros_tooling.storage.client import server_description
        print('Selected server ' + args.profile_name + ': ' + server_description(directory)['url'])
        return
    state = (args.state or (profile_directory(args.profile) if args.profile else operator_directory(workspace))).resolve()
    if args.compose_project is None:
        from micros_tooling.storage.client import config_root
        args.compose_project = ('micros-server-' + state.name
                                if state.parent == (config_root() / 'servers').resolve()
                                else 'micros-management')
    if args.action in ('start', 'shutdown'):
        import re
        require(re.fullmatch(r'[a-z0-9][a-z0-9_-]*', args.compose_project),
                'Compose project must start with a lowercase letter or digit and contain only lowercase letters, digits, hyphens or underscores.')
    if args.action == 'import-client':
        from micros_tooling.storage.client import import_operator
        print('Operator configuration: ' + str(import_operator(args.directory, state)))
        return
    if args.action == 'setup':
        require(not (state/'client.json').exists(), 'Server already configured; preserve its identity')
        try:
            address = ipaddress.ip_address(args.host)
            san = 'IP:'+args.host
            # The pinned ESP8266 TLS library only checks DNS SANs. Retain the
            # IP SAN for modern clients and the same exact name for that client.
            if address.version == 4:
                san += ',DNS:'+args.host
        except ValueError:
            import re
            require(re.fullmatch('[A-Za-z0-9.-]+', args.host), 'Invalid server hostname')
            san = 'DNS:'+args.host
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        state.chmod(0o700)
        subprocess.run(['openssl','req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256',
            '-sha256','-nodes','-days','365','-subj','/CN='+args.host,'-addext','subjectAltName='+san,
            '-keyout',str(state/'prvtkey.pem'),'-out',str(state/'servercert.pem')], check=True,capture_output=True)
        (state/'prvtkey.pem').chmod(0o600)
        atomic_write(state/'admin.token', secrets.token_hex(32).encode())
        atomic_write(state/'client.json', json.dumps(dict(url='https://'+args.host+':8443')).encode())
        print('Server identity ready. Set [management.server].url to https://'+args.host+':8443')
        return
    config = json.loads((state/'client.json').read_text())
    remote = RelayRemote(config['url'], state/'servercert.pem', state/'admin.token', getattr(args,'device_id',''),
                         cloudflare_access=config.get('cloudflare_access') is True)
    if args.action == 'publish-base':
        from micros_tooling.storage.artifacts import publish_base
        print('Base artifacts stored: ' + publish_base(remote, args.firmware))
    elif args.action == 'publish-history':
        from micros_tooling.storage.workspace import Workspace
        from micros_tooling.storage.artifacts import archive_release
        workspace = Workspace(state.parent)
        name, profile = workspace.device(args.name)
        remote.device_id = profile.get('device_id') or profile.get('mac', '').replace(':', '')
        count = 0
        for event in workspace.history(name):
            receipt = workspace.read(Path('snapshots') / event['snapshot'] / 'receipt.json')
            packages = workspace.snapshot_packages(receipt, None, verify_base=False)
            saved = workspace.root / 'snapshots' / receipt['id'] / 'configuration.json'
            configuration = json.loads(saved.read_text()) if saved.exists() else {'source': 'imported local receipt; original authored configuration unavailable'}
            archive_release(remote, receipt, packages, configuration)
            remote.raw('POST', f'/v1/artifacts/devices/{remote.device_id}/{receipt["id"]}',
                       json.dumps(dict(recorded_at=event['confirmed_at'])).encode())
            count += 1
        print(f'Archived {count} recorded deployments for {name}')
    elif args.action == 'console':
        import webbrowser
        ticket = json.loads(remote.raw('POST','/v1/console-ticket'))['ticket']
        webbrowser.open(config['url']+'/console/#ticket='+ticket)
        print('Opened management console at '+config['url']+'/console/')
    elif args.action in ('start','shutdown'):
        docker = shutil.which('docker') or '/Applications/Docker.app/Contents/Resources/bin/docker'
        command = [docker,'compose','-p',args.compose_project,'-f',str(ROOT/'src/server/compose.yaml')]
        command += ['up','--build','-d'] if args.action == 'start' else ['stop']
        subprocess.run(command, env=dict(os.environ, MICROS_SERVER_STATE=str(state)),check=True)
        if args.action == 'start':
            import http.client
            import time
            deadline = time.monotonic() + 10  # Bound readiness after the container process starts.
            while True:
                try:
                    remote.raw('GET', '/v1/devices')
                    break
                except (OSError, http.client.HTTPException):
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.25)
            print('Server ready at '+config['url'])
    elif args.action == 'enroll':
        directory = state/'enrollments'/args.device_id
        # Save the token first so an interrupted network request can be retried safely.
        if not directory.exists():
            atomic_write(directory/'relay.token', secrets.token_hex(32).encode())
            atomic_write(directory/'relay-ca.pem', (state/'servercert.pem').read_bytes())
        token = (directory/'relay.token').read_text().strip()
        require((directory/'relay-ca.pem').read_bytes() == (state/'servercert.pem').read_bytes(),
                'Enrollment belongs to a different server certificate')
        remote.raw('POST','/v1/enroll',json.dumps(dict(device_id=args.device_id,name=args.name,token=token)).encode())
        atomic_write(directory/'server.json', json.dumps(dict(url=config.get('device_url', config['url']))).encode())
        print('Enrollment ready. Base preparation needs --relay-credentials '+str(directory))
    elif args.action == 'devices':
        roster = json.loads(remote.raw('GET','/v1/devices'))
        if args.json:
            print(json.dumps(roster, indent=2))
        else:
            from datetime import datetime, timezone
            print(f"{'NAME':24} {'DEVICE ID':12} {'STATE':7} {'SERVICES':8} LAST CONTACT (UTC)")
            for device in roster['devices']:
                observed = device['status'] or {}
                contact = datetime.fromtimestamp(device['last_seen'], timezone.utc).isoformat(timespec='seconds') if device['last_seen'] else 'never'
                print(f"{device['name']:24} {device['device_id']} {'online' if device['online'] else 'offline':7} {len(observed.get('services', [])):<8} {contact}")
            if not roster['devices']:
                print('No enrolled devices. Use micros server enroll DEVICE_ID --name NAME.')
    elif args.action == 'revoke':
        remote.raw('POST','/v1/revoke',json.dumps(dict(device_id=args.device_id)).encode())
        print('Revoked '+args.device_id)
    elif args.action == 'status':
        print(json.dumps(remote.status(),indent=2))
    elif args.action == 'logs':
        print(remote.request('GET','/v1/logs'))
    elif args.action in ('stop', 'recover', 'reboot'):
        status = remote.status()
        with remote.deployment_session(status):
            if args.action == 'recover':
                selected = status['activation']
                require(not selected['pending'] and selected['good'] in (0,1), 'No recoverable selected application')
                result = remote.request('POST', '/v1/activate?bank='+str(selected['good']), bytes.fromhex(selected['good_sha256']))
            else:
                result = remote.request('POST','/v1/pause' if args.action == 'stop' else '/v1/reboot')
        print(json.dumps(result,indent=2))
    elif args.action == 'bind':
        from micros_tooling.storage.workspace import Workspace
        workspace = Workspace(Path(os.environ.get('MICROS_STATE_DIR',ROOT/'.micros')))
        with workspace.locked():
            name, profile = workspace.device(args.name)
            status = remote.status()
            identity = status['identity']
            from micros_tooling.deployment.identity import verify_base
            verify_base(status, workspace.files(name)[2])
            expected = profile.get('device_id') or profile.get('mac','').replace(':','')
            require(not expected or expected == args.device_id, 'Relay device differs from saved pairing')
            directory = workspace.root/'devices'/name
            atomic_write(directory/'relay-ca.pem',(state/'servercert.pem').read_bytes())
            atomic_write(directory/'relay-admin.token',(state/'admin.token').read_bytes())
            profiles = workspace.profiles()
            profiles['devices'][name]['relay'] = dict(url=config['url'],device_id=identity['device_id'],
                                                     cloudflare_access=config.get('cloudflare_access') is True)
            workspace.write('devices.json', profiles)
        print('Management for '+name+' now uses '+config['url'])


def configured_remote(workspace, device_id=''):
    """Return the operator's default server without requiring a local device pairing."""
    from micros_tooling.storage.client import operator_directory
    directory = operator_directory(workspace)
    if not (directory/'client.json').exists():
        return None
    config = json.loads((directory/'client.json').read_text())
    return RelayRemote(config['url'],directory/'servercert.pem',directory/'admin.token',device_id,
                       cloudflare_access=config.get('cloudflare_access') is True)


def choose_device(devices, requested=None, interactive=False, ask=input, require_online=True):
    """Select from current server presence, never from USB enumeration or stale local defaults."""
    if requested:
        matches=[device for device in devices if requested in (device['device_id'],device['name'])]
        require(len(matches)==1, 'Server device name/ID is unknown or ambiguous. Run micros devices.')
        require(not require_online or matches[0]['online'], 'Device is offline at the server; last contact: '+str(matches[0]['last_seen']))
        return matches[0]
    available=[device for device in devices if not require_online or device['online']]
    require(available, 'No devices are online at the management server. Run micros devices for last contact times.')
    if len(available)==1:
        return available[0]
    choices='\n'.join(f"  {index}. {device['name']} ({device['device_id']})" for index,device in enumerate(available,1))
    require(interactive, 'Choose a server device with -d NAME or -d DEVICE_ID:\n'+choices)
    print('Available devices:\n'+choices, file=sys.stderr)
    selected=ask('Device number: ').strip()
    require(selected.isdigit() and 1<=int(selected)<=len(available), 'Invalid device selection')
    return available[int(selected)-1]


def discover_for_command(workspace, args):
    """Resolve server identity; profiles for artifact commands are disposable routing caches."""
    remote=configured_remote(workspace)
    if remote is None:
        return None
    devices=json.loads(remote.raw('GET','/v1/devices'))['devices']
    selected=choose_device(devices,args.device,sys.stdin.isatty(),
                           require_online=args.command != 'history')
    remote.device_id=selected['device_id']
    args.device=selected['device_id']
    if args.command in ('build', 'deploy', 'rollback', 'history'):
        name = selected['device_id']
        with workspace.locked():
            current = workspace.profiles()
            # Store routing metadata only. Names and presence always come from the server.
            previous = current['devices'].get(name)
            if previous:
                require((previous.get('device_id') or previous.get('mac', '').replace(':', '')) == name,
                        'Local profile conflicts with server hardware identity')
            current['devices'].setdefault(name, dict(device_id=name, host=remote.host, transport='native'))
            workspace.write('devices.json', current)
        return remote, selected, True
    return remote, selected, False
