"""Choose enrollment's destination before authentication or USB access."""
from contextlib import contextmanager
import os
from pathlib import Path

from micros_tooling.storage import client
from micros_tooling.storage.packages import require


def prompt(label, validate, default=None):
    from micros_tooling.deployment.enrollment import progress, EnrollmentCancelled
    while True:
        answer = input(label + (f' [{default}]' if default is not None else '') + ': ').strip()
        if answer.lower() == 'q':
            raise EnrollmentCancelled('Enrollment canceled.')
        try:
            return validate(answer or (str(default) if default is not None else ''))
        except ValueError as error:
            progress(str(error))


def port_available(port):
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(('0.0.0.0', port))
        return True
    except OSError:
        return False


def local_address():
    import socket
    try:
        # UDP connect selects the local route without sending a packet.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.connect(('192.0.2.1', 9))
            return connection.getsockname()[0]
    except OSError:
        return None


def choose_server(workspace):
    from micros_tooling.deployment.enrollment import progress, EnrollmentCancelled
    from micros_tooling.fleet.server import server_main, server_address
    profiles = client.saved_servers(workspace)
    current = client.operator_directory(workspace).resolve() if client.explicit_selection() else None
    default = None
    progress('Choose the server to enroll this controller into:')
    for index, profile in enumerate(profiles, 1):
        selected = Path(profile['directory']) == current
        if selected and 'error' not in profile:
            default = str(index)
        progress(f'{index}. {profile["name"]} · ' + profile.get('url', profile.get('error', 'incomplete'))
                 + (' · Cloudflare Access' if profile.get('cloudflare_access') else '')
                 + (' · selected' if selected else ''))
    progress('a. Connect to an existing server (import operator bundle)')
    progress('n. Create a new server on this computer')
    progress('q. Cancel (also available at the following prompts)')
    def menu(answer):
        answer = answer.lower()
        if answer.isdigit() and 1 <= int(answer) <= len(profiles):
            profile = profiles[int(answer) - 1]
            require('error' not in profile, profile.get('error', 'Invalid server profile'))
            return answer
        require(answer in ('a', 'n'), 'Choose a displayed server number, a, n or q.')
        return answer
    choice = prompt('Server', menu, default)
    if choice.isdigit():
        profile = profiles[int(choice) - 1]
        return client.select_server(profile['name'], directory=profile['directory'])
    def profile_name(name):
        directory = client.profile_directory(name)
        require(not directory.exists(), 'That profile already exists; choose a new name or q to return later.')
        return name
    name = prompt('Name for this server profile', profile_name)
    if choice == 'a':
        progress('Use a directory containing client.json, servercert.pem and admin.token from the server operator.')
        def import_bundle(source):
            require(source, 'An operator bundle directory is required.')
            server_main(['--profile', name, 'import-client', source])
        prompt('Operator bundle directory', import_bundle)
    else:
        def reachable_host(host):
            import ipaddress
            server_address(host)
            require(host.lower().rstrip('.') != 'localhost', 'A board cannot reach localhost. Use this computer’s LAN address.')
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                pass
            else:
                require(not address.is_loopback, 'A board cannot reach a loopback address. Use this computer’s LAN address.')
            return host
        host = prompt('Hostname or LAN IP of this computer reachable by your board', reachable_host, local_address())
        def available_port(value):
            require(value.isdecimal() and 1 <= int(value) <= 65535, 'Enter a TCP port from 1 to 65535.')
            port = int(value)
            require(port_available(port), f'TCP port {port} is unavailable on this computer; choose another port.')
            return port
        default_port = next((port for port in (8443, 18443, 28443) if port_available(port)), 8443)
        port = prompt('HTTPS port', available_port, default_port)
        server_main(['--profile', name, 'setup', '--host', host, '--port', str(port)])
        client.select_server(name)
        progress(f'Server saved at {server_address(host, port)[0]}. Starting it requires Docker with Compose.')
        if input('Start this server now? [y/N]: ').strip().lower() not in ('y', 'yes'):
            raise EnrollmentCancelled(f'Server saved. Run micros server --profile {name} start, then rerun enroll.')
        server_main(['--profile', name, 'start'])
    return client.select_server(name)


@contextmanager
def enrollment_server(args):
    from micros_tooling.deployment.enrollment import interactive, progress, ROOT
    from micros_tooling.storage.workspace import Workspace
    if args.detect:
        yield
        return
    project = client.application_root()
    previous = {key: os.environ.get(key) for key in ('MICROS_CLIENT_DIR', 'MICROS_STATE_DIR')}
    previous_cache = client.application_cache(project) if project else None
    workspace = Workspace(Path(previous['MICROS_STATE_DIR'] or ROOT / '.micros'))
    name = getattr(args, 'server', None)
    if name:
        require(not os.environ.get('MICROS_CLIENT_DIR') and not os.environ.get('MICROS_SERVER'),
                'Unset MICROS_CLIENT_DIR and MICROS_SERVER before choosing --server.')
        directory = client.select_server(name)
    elif os.environ.get('MICROS_CLIENT_DIR') or os.environ.get('MICROS_SERVER'):
        directory = client.operator_directory(workspace)
    elif interactive(args):
        directory = choose_server(workspace)
    else:
        require(client.explicit_selection(),
                'Choose a server first: micros server list, then micros server use NAME; '
                'or pass enroll --server NAME. Interactive enroll can connect or create a server.')
        directory = client.operator_directory(workspace)
    description = client.server_description(directory)
    progress('Enrollment server: ' + description['url'] + ' (' + str(directory) + ')'
             + (' · Cloudflare Access authentication required' if description['cloudflare_access'] else ''))
    try:
        os.environ['MICROS_CLIENT_DIR'] = str(directory.resolve())
        if project and (previous['MICROS_STATE_DIR'] is None
                        or Path(previous['MICROS_STATE_DIR']).resolve() == previous_cache.resolve()):
            os.environ['MICROS_STATE_DIR'] = str(client.application_cache(project))
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
