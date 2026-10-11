"""Live device access shared by the shell and its noninteractive command mode."""
import json
import http.client
from micros_tooling.communication.remote import RemoteRejected
from micros_tooling.communication.channel_metadata import validate_bindings
from micros_tooling.storage.packages import require


def pick_device(devices, *, ask=None, output=None):
    """Always offer an explicit choice, including when only one board is enrolled."""
    import sys
    from micros_tooling.terminal.shell import safe_text
    ask = ask or input
    output = output or sys.stdout
    require(devices, 'No enrolled devices. Run micros devices.')
    ordered = sorted(devices, key=lambda d: (not d['online'], d['name'], d['device_id']))
    print('  Choose a device\n', file=output)
    print('     DEVICE                    STATE     ID', file=output)
    for index, device in enumerate(ordered, 1):
        name = safe_text(device['name'])[:24]
        state = 'online' if device['online'] else 'offline'
        print(f"  {index}. {name:<24}  {state:<8}  {device['device_id']}", file=output)
    print(file=output)
    while True:
        try:
            choice = ask('Device number (q to cancel): ').strip()
        except EOFError:
            raise KeyboardInterrupt from None
        if choice.lower() in ('q', 'quit'):
            raise KeyboardInterrupt
        if choice.isascii() and choice.isdecimal() and 1 <= int(choice) <= len(ordered):
            return ordered[int(choice) - 1]
        print('Enter a listed device number, or q to cancel.', file=output)


class DeviceClient:
    def __init__(self, workspace, requested, *, interactive=False):
        self.workspace = workspace
        self.requested = requested
        self.interactive = interactive
        self.remote = None
        self.name = requested or 'device'
        self.identity = None
        self.inspection_supported = None

    def connect(self):
        from micros_tooling.fleet.server import configured_remote, choose_device
        from micros_tooling.deployment.diagnostics import connect
        remote = configured_remote(self.workspace)
        if remote is not None:
            roster = json.loads(remote.raw('GET', '/v1/devices'))['devices']
            requested = self.identity or self.requested
            if requested:
                selected = choose_device(roster, requested, require_online=False)
            else:
                require(self.interactive, 'Specify -d DEVICE for noninteractive shell commands.')
                selected = pick_device(roster)
            remote.device_id = selected['device_id']
            self.name = selected['name']
            self.identity = selected['device_id']
        else:
            name, profile, remote = connect(self.workspace, self.requested)
            identity = profile.get('device_id') or profile.get('mac', '').replace(':', '') or None
            require(not self.identity or not identity or self.identity == identity,
                    'Saved profile changed device identity; start a new shell for the new device.')
            self.name = name
            self.identity = self.identity or identity
        self.remote = remote
        self.inspection_supported = None

    def status(self):
        if self.remote is None:
            self.connect()
        if hasattr(self.remote, 'raw') and self.inspection_supported is not False:
            try:
                status = json.loads(self.remote.raw('GET', '/v1/inspect/' + self.remote.device_id))
                self.inspection_supported = True
            except RemoteRejected as error:
                if error.status != 404:
                    raise
                self.inspection_supported = False
                status = self.remote.status()
        else:
            status = self.remote.status()
        observed = status.get('identity', {}).get('device_id')
        require(not self.identity or observed == self.identity
                or observed is None and not hasattr(self.remote, 'raw'),
                'Device identity changed; start a new shell for the new device.')
        if observed:
            self.identity = observed
        validate_bindings(status.get('channel_ports', []))
        from micros_tooling.commands.metadata import validate_bindings as validate_commands
        validate_commands(status.get('service_commands', []))
        return status

    def binding(self, service, port):
        status = self.status()
        require(self.inspection_supported is True,
                'Service discovery requires the updated management server and a registered release.')
        require(not status.get('activation', {}).get('pending'), 'Application trial pending; wait for confirmation.')
        matches = [b for b in status.get('channel_ports', [])
                   if b['service'] == service and b['port']['name'] == port]
        require(len(matches) == 1, 'No matching published port. Run ports to discover available names.')
        return status, matches[0]

    def command_definition(self, service, command):
        status = self.status()
        for binding in status.get('service_commands', []):
            if binding['service'] == service and command in binding['contract']['exposed']:
                return status, binding['contract']['commands'][command]
        return status, None

    def invoke(self, service, command, arguments):
        from micros_tooling.commands.schema import parse_arguments
        status, definition = self.command_definition(service, command)
        require(definition is not None, 'No matching command in the live release. Run commands to discover exposed commands.')
        values = parse_arguments(definition['args'], arguments)
        payload = dict(base=status['identity']['base_sha256'], graph=status['activation']['good_sha256'],
                       service=service, command=command, args=values)
        return json.loads(self.remote.raw('POST', '/v1/commands/' + self.remote.device_id, json.dumps(payload).encode()))

    def samples(self, service, port, *, seconds=None, once=False, clock=None):
        import time
        from micros_tooling.diagnostics.collect import stream
        clock = clock or time.monotonic
        status, _ = self.binding(service, port)
        opened = stream(self.remote, dict(action='open', base=status['identity']['base_sha256'],
                                         graph=status['activation']['good_sha256'], service=service, port=port))
        deadline = clock() + seconds if seconds is not None else None
        cursor = opened['cursor']
        try:
            while deadline is None or clock() < deadline:
                reply = stream(self.remote, dict(action='read', reader=opened['reader'], cursor=cursor))
                cursor = reply['cursor']
                for event in reply['events']:
                    yield event
                if once:
                    if not reply['events']:
                        yield dict(state='empty')
                    return
        finally:
            try:
                stream(self.remote, dict(action='close', reader=opened['reader']))
            except (OSError, ValueError, http.client.HTTPException):
                # The server expires disconnected reader leases after 30 seconds.
                pass
