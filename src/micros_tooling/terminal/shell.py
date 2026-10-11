"""A local, bounded command vocabulary over authenticated micros management APIs."""
import argparse
import http.client
import json
import math
import os
from pathlib import Path
import shlex
import ssl
import sys
import time
from contextlib import contextmanager

from micros_tooling.communication.logs import follow_logs
from micros_tooling.communication.remote import RemoteRejected
from micros_tooling.storage.packages import require
from micros_tooling.terminal.client import DeviceClient

def readline_backend():
    # CPython's libedit input can leave Ctrl-D as literal input after Ctrl-C.
    # Completion and history must use the same backend as the input editor.
    if sys.platform == 'darwin':
        import gnureadline as readline
    else:
        import readline
    return readline


HELP = {
    'ls': 'ls [INDEX|NAME] — list services (alias for services)',
    'status': 'status [--details] [--json] — live identity, activation, memory and service summary',
    'services': 'services [INDEX|NAME] [--details] [--json] — list services or inspect one service',
    'logs': 'logs [--follow] [--json] — recent logs or continuous output; Ctrl-C returns to prompt',
    'watch': 'watch [--interval SECONDS] [--count N] [status|services] — repeat read-only inspection',
    'commands': 'commands [SERVICE] — list commands published by the deployed release',
    'ports': 'ports [SERVICE] — list published service ports',
    'call': 'call SERVICE COMMAND FIELD=VALUE ... — send one typed service command (never retried)',
    'read': 'read SERVICE PORT — read telemetry through a shared capture lease',
    'follow': 'follow SERVICE PORT [--seconds N] — stream telemetry; Ctrl-C closes the lease',
    'restart': 'restart INDEX — restart one service using the existing guarded operation',
    'reconnect': 'reconnect — refresh credentials and reconnect to the same device identity',
    'history': 'history — show commands from this session',
    'help': 'help [COMMAND] or help call SERVICE COMMAND — usage and service field bounds',
    'exit': 'exit (or quit / Ctrl-D) — close the local shell',
}


def safe_text(value):
    """Device logs and release labels must not inject terminal control sequences."""
    return ''.join(c if c in '\n\t' or c.isprintable() else f'\\x{ord(c):02x}' for c in str(value))


def size(value):
    if value is None:
        return 'Unknown'
    for unit in ('B', 'KiB', 'MiB', 'GiB'):
        if abs(value) < 1024 or unit == 'GiB':
            return f'{value:.0f} {unit}' if unit == 'B' else f'{value:.1f} {unit}'
        value /= 1024


def duration(microseconds):
    if microseconds is None:
        return 'Unknown'
    seconds = int(microseconds / 1000000)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = ([f'{days}d'] if days else []) + ([f'{hours}h'] if hours else [])
    if minutes or parts:
        parts.append(f'{minutes}m')
    return ' '.join(parts) if parts else f'{seconds}s'


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message + '; run help ' + self.prog)

    def exit(self, status=0, message=None):
        raise ValueError(message or self.format_help())


def options(command, args):
    p = Parser(prog=command, add_help=False, allow_abbrev=False)
    if command in ('status', 'services', 'logs'):
        p.add_argument('--json', action='store_true')
    if command in ('status', 'services'):
        p.add_argument('--details', action='store_true')
    if command == 'services':
        p.add_argument('service', nargs='?')
    if command == 'logs':
        p.add_argument('--follow', '-f', action='store_true')
    if command == 'watch':
        p.add_argument('--interval', '-n', type=float, default=2)
        p.add_argument('--count', type=int)
        p.add_argument('view', nargs='?', default='status', choices=('status', 'services'))
    if command in ('read', 'follow'):
        p.add_argument('service')
        p.add_argument('port')
        if command == 'follow':
            p.add_argument('--seconds', type=float)
    return p.parse_args(args)


def interruptible_sleep(seconds):
    # A SIGINT received while rendering can remain pending until the next
    # interpreter check. Bound each native sleep so watch returns promptly even
    # when that signal did not interrupt the sleep syscall itself.
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 0.25))


class Shell:
    def __init__(self, client, *, output=None, sleep=interruptible_sleep):
        self.client = client
        self.output = output or sys.stdout
        self.sleep = sleep
        self.history = []
        self.bindings = []
        self.command_bindings = []
        self.service_names = []
        self.connected = False
        self.last_identity = None

    def write(self, value=''):
        print(safe_text(value), file=self.output, flush=True)

    def snapshot(self, notices=True):
        status = self.client.status()
        identity = (status.get('service_boot'), status.get('activation', {}).get('sequence'),
                    status.get('activation', {}).get('good_sha256'))
        if notices and self.last_identity is not None and identity != self.last_identity:
            self.write('Device boot or application changed; refreshed service discovery.')
        if notices and not self.connected:
            self.write(f'Connected: {self.client.name} ({self.client.identity or "saved profile"})')
        self.last_identity = identity
        self.connected = True
        self.bindings = status.get('channel_ports', [])
        self.command_bindings = status.get('service_commands', [])
        self.service_names = [s.get('name', str(i)) for i, s in enumerate(status.get('services', []))]
        return status

    def fields(self, pairs):
        for label, value in pairs:
            self.write(f'  {label:<14} {value}')

    def service_table(self, services, details=False):
        self.write()
        self.write('  ID   SERVICE                        STATE' + ('       RESULT  STEPS       CALLBACKS' if details else ''))
        for index, service in enumerate(services):
            name = safe_text(service.get('name', f'Service {index}'))
            if len(name) > 29:
                name = name[:26] + '...'
            state = service.get('state', 'Unknown')
            result = service.get('result', 0)
            row = f'  {index:<4} {name:<30} {state}'
            if details:
                row = f'  {index:<4} {name:<30} {state:<11} {result:<7} {service.get("steps", 0):<11} {service.get("callbacks", 0)}'
            elif result:
                row += f' (error {result})'
            self.write(row)
        if not services:
            self.write('  No loaded services.')
        elif any(not service.get('name') for service in services):
            self.write('  Names unavailable from this release; use the ID to inspect a service.')
        self.write()

    def display(self, status, command, parsed):
        services = status.get('services', [])
        if command == 'services' and parsed.service is not None:
            selected = [(i, v) for i, v in enumerate(services) if parsed.service in (str(i), v.get('name'))]
            require(len(selected) == 1, 'Unknown or ambiguous service index/name.')
            index, service = selected[0]
            if parsed.json:
                self.write(json.dumps(service, indent=2))
            else:
                self.write(f'\n  {service.get("name", f"Service {index}")}')
                self.fields([(key.replace('_', ' ').capitalize(), value) for key, value in service.items()])
                self.write()
            return
        if parsed.json:
            self.write(json.dumps(status if command == 'status' else services, indent=2))
            return
        if command == 'status':
            activation = status.get('activation', {})
            network = status.get('network', {})
            memory = status.get('memory', {})
            running = sum(v.get('state') == 'Running' and not v.get('result') for v in services)
            application = 'Trial pending' if activation.get('pending') else 'Confirmed' if activation.get('good', 0) in (0, 1) else 'No selected application'
            if status.get('physical_recovery'):
                application = 'Physical recovery'
            if status.get('deployment_session'):
                application += ' · update in progress'
            self.write(f'\n  {self.client.name}  /  {status.get("platform", "unknown")}')
            self.fields([
                ('Uptime', duration(status.get('uptime_us'))),
                ('Application', application),
                ('Services', f'{running} of {len(services)} running'),
                ('Network', (network.get('ip', 'Connected') if network.get('connected') else 'Disconnected')
                 + (f"  ({network['rssi_dbm']} dBm)" if network.get('connected') and 'rssi_dbm' in network else '')),
                ('Free RAM', size(memory.get('internal_free', status.get('heap')))),
            ])
            if memory.get('psram_total'):
                self.fields([('Free PSRAM', size(memory.get('psram_free')))])
            if parsed.details:
                self.write()
                self.fields([('Device ID', self.client.identity or 'Unknown'),
                             ('Graph', activation.get('good_sha256', 'Unknown')),
                             ('Sequence', activation.get('sequence', 'Unknown'))])
                for title in ('memory', 'network'):
                    self.write(f'\n  {title.capitalize()} details')
                    self.fields([(k.replace('_', ' '), v) for k, v in status.get(title, {}).items()])
            else:
                self.write('\n  status --details  Full identifiers and counters')
            self.write()
        else:
            self.service_table(services, parsed.details)

    def overview_help(self):
        groups = [
            ('Inspect', [('status', 'Board summary'), ('ls', 'List services'),
                         ('services 0', 'Inspect one service'), ('logs --follow', 'Stream logs'),
                         ('watch services', 'Monitor service state')]),
            ('Service commands', [('commands', 'Discover available commands'), ('ports', 'Discover published channels'),
                                  ('call / read / follow', 'Send a command or inspect telemetry')]),
            ('Session', [('restart 0', 'Restart one service'), ('reconnect', 'Reconnect to this board'),
                         ('history', 'Recent commands'), ('exit', 'Close the shell')]),
        ]
        for title, commands in groups:
            self.write(f'\n  {title}')
            for command, description in commands:
                self.write(f'    {command:<24} {description}')
        self.write('\n  help COMMAND  Usage and options')
        self.write('  Ctrl-C        Stop the current command')
        self.write('  Ctrl-D        Exit\n')

    def list_ports(self, command, args):
        require(len(args) <= 1, HELP[command])
        self.snapshot()
        bindings = [b for b in self.bindings if (not args or b['service'] == args[0])
                    and command == 'ports']
        from micros_tooling.commands.schema import describe
        typed = [b for b in self.command_bindings if command == 'commands' and (not args or b['service'] == args[0])]
        for binding in typed:
            self.write(f'\n  {binding["service"]}')
            for name in binding['contract']['exposed']:
                definition = binding['contract']['commands'][name]
                self.write(f'    {name:<22} {definition["description"]}')
                for field, spec in definition['args'].items():
                    self.write(f'      {field}: {describe(spec)}')
        for b in bindings:
            v = b['port']
            self.write(f"{b['service']} {v['name']} (channel {v['key']})")
        if not bindings and not typed:
            self.write('No matching commands in the live release. Declare service.commands and expose_commands in the board unit.'
                       if command == 'commands' else 'No matching published ports in the live release. Add bridge subscriptions.')
            if self.client.inspection_supported is not True:
                self.write('Discovery requires the updated management server; basic status and logs remain available.')

    def execute(self, line):
        require(len(line) <= 4096, "Command exceeds 4096 characters.")
        args = shlex.split(line)
        if not args:
            return True
        command, args = args[0], args[1:]
        if command == 'ls':
            command = 'services'
        if command in ('exit', 'quit'):
            require(not args, 'exit takes no arguments')
            return False
        require(command in HELP, 'Unknown command. Run help for available commands.')
        self.history.append(line)
        self.history = self.history[-500:]
        if command == 'help':
            if len(args) == 3 and args[0] == 'call':
                _, definition = self.client.command_definition(args[1], args[2])
                if definition is not None:
                    from micros_tooling.commands.schema import describe
                    self.write(definition['description'])
                    for label, fields in [('Arguments', definition['args']), ('Returns', definition['returns'])]:
                        self.write('  ' + label + (':' if fields else ': none'))
                        for field, spec in fields.items():
                            self.write(f'    {field}: {describe(spec)}')
                else:
                    raise ValueError('No matching typed command in the live release.')
            else:
                require(len(args) <= 1 and (not args or args[0] in HELP), HELP['help'])
                if args:
                    self.write(HELP[args[0]])
                else:
                    self.overview_help()
        elif command == 'history':
            require(not args, HELP[command])
            for i, entry in enumerate(self.history, 1):
                self.write(f'{i:4}  {entry}')
        elif command == 'reconnect':
            require(not args, HELP[command])
            self.connected = False
            self.client.connect()
            self.snapshot()
        elif command in ('status', 'services'):
            parsed = options(command, args)
            self.display(self.snapshot(notices=not parsed.json), command, parsed)
        elif command == 'logs':
            parsed = options(command, args)
            status = self.snapshot(notices=not parsed.json)
            if 'identity' not in status:
                require(not parsed.follow, 'This base supports a one-shot log tail only.')
                tail = self.client.remote.request('GET', '/v1/logs')
                self.write(json.dumps(dict(event='logs', logs=tail)) if parsed.json else tail)
            else:
                for event in follow_logs(self.client.remote, parsed.follow):
                    if parsed.json or event['event'] != 'logs':
                        self.write(json.dumps(event))
                    else:
                        print(safe_text(event['logs']), end='', file=self.output, flush=True)
        elif command == 'watch':
            parsed = options(command, args)
            require(math.isfinite(parsed.interval) and 0.25 <= parsed.interval <= 3600, 'Interval must be 0.25..3600 seconds.')
            require(parsed.count is None or 1 <= parsed.count <= 100000, 'Count must be 1..100000.')
            count = 0
            while parsed.count is None or count < parsed.count:
                try:
                    self.display(self.snapshot(), parsed.view, options(parsed.view, []))
                except (OSError, http.client.HTTPException, RemoteRejected) as error:
                    if not self.transient(error):
                        raise
                    self.report(error)
                count += 1
                if parsed.count is None or count < parsed.count:
                    self.sleep(parsed.interval)
        elif command in ('commands', 'ports'):
            self.list_ports(command, args)
        elif command == 'call':
            require(len(args) >= 2, HELP[command])
            values = {}
            for assignment in args[2:]:
                key, sep, raw = assignment.partition('=')
                require(sep and key and key not in values, 'Use unique FIELD=VALUE arguments.')
                values[key] = raw
            reply = self.client.invoke(args[0], args[1], values)
            if reply.get('state') == 'completed':
                self.write()
                self.fields([(key, value) for key, value in reply.get('values', {}).items()])
                if not reply.get('values'):
                    self.write('  Completed.')
                self.write()
            elif reply.get('state') in ('failed', 'unknown'):
                raise ValueError(f"{reply['state']}: {reply.get('message', '')} (result {reply.get('result', 'unknown')}, request {reply.get('request_id', '?')})")
            else:
                self.write(json.dumps(reply))
        elif command in ('read', 'follow'):
            parsed = options(command, args)
            seconds = getattr(parsed, 'seconds', None)
            require(seconds is None or math.isfinite(seconds) and 0 < seconds <= 86400, 'Seconds must be greater than zero and at most 86400.')
            samples = self.client.samples(parsed.service, parsed.port, once=command == 'read', seconds=seconds)
            try:
                for sample in samples:
                    self.write(json.dumps(sample))
            finally:
                samples.close()
        elif command == 'restart':
            require(len(args) == 1 and args[0].isascii() and args[0].isdecimal(), HELP[command])
            self.snapshot()
            from micros_tooling.deployment.service_control import restart_service
            restart_service(self.client.remote, int(args[0]))
            self.write(f'Service {args[0]} restarted; peers preserved.')
        return True

    @staticmethod
    def transient(error):
        if isinstance(error, ssl.SSLError):
            return False
        if isinstance(error, RemoteRejected):
            return error.status in (409, 503, 504)
        return isinstance(error, (OSError, http.client.HTTPException))

    def report(self, error, *, mutation=False):
        if self.transient(error):
            self.connected = False
            self.bindings = []
            self.write('Connection unavailable: ' + str(error))
        else:
            self.write('Error: ' + str(error))
        if mutation:
            self.write('Command was not retried. If dispatch began, its outcome may be unknown; inspect status/logs before retrying.')

    def run_line(self, line):
        try:
            return self.execute(line), 0
        except KeyboardInterrupt:
            self.write('\nInterrupted; returned to prompt. In-flight writes are not undone or retried.')
            return True, 130
        except (ValueError, RuntimeError, OSError, http.client.HTTPException, KeyError, TypeError) as error:
            self.report(error, mutation=line.lstrip().split(' ', 1)[0] in ('call', 'restart'))
            return True, 1

    def complete(self, text, state):
        readline = readline_backend()
        line = readline.get_line_buffer()[:readline.get_begidx()]
        try:
            words = shlex.split(line)
        except ValueError:
            return None
        choices = list(HELP) + ['quit'] if not words else []
        if words and words[0] in ('ls', 'services', 'commands', 'ports', 'call', 'read', 'follow'):
            if len(words) == 1:
                choices = self.service_names
            elif len(words) == 2 and words[0] in ('call', 'read', 'follow'):
                choices = [b['port']['name'] for b in self.bindings if b['service'] == words[1]] if words[0] != 'call' else []
                if words[0] == 'call':
                    choices += [c for b in self.command_bindings if b['service'] == words[1] for c in b['contract']['exposed']]
            elif len(words) >= 3 and words[0] == 'call':
                choices = []
                choices += [field + '=' for b in self.command_bindings if b['service'] == words[1]
                            and words[2] in b['contract']['exposed']
                            for field in b['contract']['commands'][words[2]]['args']
                            if not any(w.startswith(field + '=') for w in words[3:])]
                if '=' in text:
                    field, prefix = text.split('=', 1)
                    for binding in self.command_bindings:
                        if binding['service'] != words[1] or words[2] not in binding['contract']['exposed']:
                            continue
                        spec = binding['contract']['commands'][words[2]]['args'].get(field, {})
                        options = spec.get('choices', []) if spec.get('type') == 'enum' else ['true', 'false'] if spec.get('type') == 'bool' else []
                        choices += [field + '=' + value for value in options if value.startswith(prefix)]
        elif words and words[0] == 'help':
            choices = list(HELP)
        elif words and words[0] == 'watch':
            choices = ['status', 'services', '--interval', '--count']
        elif words and words[0] == 'logs':
            choices = ['--follow', '--json']
        matches = sorted(c for c in set(choices) if c.startswith(text))
        return matches[state] if state < len(matches) else None

    def interact(self, read=input):
        self.write('\n  micros shell\n')
        try:
            status = self.snapshot(notices=False)
            services = status.get('services', [])
            running = sum(v.get('state') == 'Running' and not v.get('result') for v in services)
            self.write(f'\n  Connected to {self.client.name}  ·  {status.get("platform", "unknown")}')
            self.write(f'  {running}/{len(services)} services running  ·  up {duration(status.get("uptime_us"))}')
            if status.get('physical_recovery') or status.get('activation', {}).get('pending') or status.get('deployment_session'):
                self.write('  Recovery, trial or update active — run status for details.')
        except (KeyboardInterrupt, EOFError):
            self.write()
            return 0
        except (ValueError, OSError, http.client.HTTPException, KeyError, TypeError) as error:
            self.report(error)
        self.write('\n  status  Board summary    ls  Services    help  All commands\n')
        while True:
            try:
                line = read(safe_text(self.client.name) + '> ')
            except EOFError:
                self.write()
                return 0
            except KeyboardInterrupt:
                self.write()
                continue
            keep, _ = self.run_line(line)
            if not keep:
                return 0


@contextmanager
def line_editor(shell, history_file):
    try:
        readline = readline_backend()
    except ImportError:
        yield
        return
    previous = readline.get_completer()
    delimiters = readline.get_completer_delims()
    readline.set_completer(shell.complete)
    readline.set_completer_delims(' \t\n')
    readline.parse_and_bind('bind ^I rl_complete' if 'libedit' in (readline.__doc__ or '') else 'tab: complete')
    readline.set_history_length(500)
    readline.clear_history()
    path = Path(history_file) if history_file else None
    if path:
        try:
            if path.exists():
                require(not path.is_symlink() and path.is_file(), 'History must be a regular file.')
                readline.read_history_file(str(path))
        except (OSError, ValueError) as error:
            shell.write('History unavailable: ' + str(error))
            path = None
    try:
        yield
    finally:
        if path:
            try:
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                # Never follow a substituted symlink or loosen history permissions.
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, 'w') as history:
                    history.truncate(0)
                    start = max(1, readline.get_current_history_length() - 499)
                    for index in range(start, readline.get_current_history_length() + 1):
                        history.write(readline.get_history_item(index) + '\n')
            except OSError as error:
                shell.write('Could not save history: ' + str(error))
        readline.set_completer(previous)
        readline.set_completer_delims(delimiters)


def main(args):
    p = argparse.ArgumentParser(prog='micros shell', description=__doc__)
    p.add_argument('-d', '--device', help='server device name/ID or saved local profile')
    p.add_argument('-c', '--command', action='append', help='run a shell command and exit; repeat for a sequence')
    p.add_argument('--no-history', action='store_true', help='disable persistent command history')
    p.add_argument('--history-file', type=Path, default=Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'micros/shell_history')
    options = p.parse_args(args)
    from micros_tooling.storage.workspace import Workspace
    from micros_tooling.config.repository import ROOT
    client = DeviceClient(Workspace(Path(os.environ.get('MICROS_STATE_DIR', ROOT / '.micros'))), options.device,
                          interactive=sys.stdin.isatty() and not options.command)
    shell = Shell(client)
    if options.command:
        for line in options.command:
            keep, code = shell.run_line(line)
            if code or not keep:
                return code
        return 0
    if not sys.stdin.isatty():
        for line in sys.stdin:
            keep, code = shell.run_line(line)
            if code or not keep:
                return code
        return 0
    with line_editor(shell, None if options.no_history else options.history_file):
        return shell.interact()
