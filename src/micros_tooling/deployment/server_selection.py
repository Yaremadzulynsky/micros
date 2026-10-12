"""Choose enrollment's destination before authentication or USB access."""
from contextlib import contextmanager
import os
from pathlib import Path

from micros_tooling.storage import client
from micros_tooling.storage.packages import require


def choose_server(workspace):
    from micros_tooling.deployment.enrollment import progress, EnrollmentCancelled
    from micros_tooling.fleet.server import server_main
    profiles = client.saved_servers(workspace)
    current = client.operator_directory(workspace).resolve() if client.explicit_selection() else None
    progress('Choose the server to enroll this controller into:')
    for index, profile in enumerate(profiles, 1):
        progress(f'{index}. {profile["name"]} · ' + profile.get('url', profile.get('error', 'incomplete'))
                 + (' · Cloudflare Access' if profile.get('cloudflare_access') else '')
                 + (' · selected' if Path(profile['directory']) == current else ''))
    progress('a. Connect to an existing server (import operator bundle)')
    progress('n. Create a new server on this computer')
    progress('q. Cancel')
    choice = input('Server: ').strip().lower()
    if choice == 'q':
        raise EnrollmentCancelled('Enrollment canceled before connecting to a server.')
    if choice.isdigit() and 1 <= int(choice) <= len(profiles):
        profile = profiles[int(choice) - 1]
        require('error' not in profile, profile.get('error', 'Invalid server profile'))
        return client.select_server(profile['name'], directory=profile['directory'])
    require(choice in ('a', 'n'), 'Choose a displayed server number, a, n or q.')
    name = input('Name for this server profile: ').strip()
    directory = client.profile_directory(name)
    require(not directory.exists(), 'That profile already exists; choose it from the list or use a new name.')
    if choice == 'a':
        progress('Use a directory containing client.json, servercert.pem and admin.token from the server operator.')
        source = input('Operator bundle directory: ').strip()
        require(source, 'An operator bundle directory is required.')
        server_main(['--profile', name, 'import-client', source])
    else:
        host = input('Hostname or LAN IP of this computer reachable by your board: ').strip()
        server_main(['--profile', name, 'setup', '--host', host])
        client.select_server(name)
        progress('Starting a local server requires Docker with Compose and an available TCP port 8443.')
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
