"""Local native application builds and managed deployment (Linux and macOS ARM64)."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

from micros_tooling.host import daemon
from micros_tooling.config.layout import host_directory
from micros_tooling.host.activation import read_record, stage
from micros_tooling.storage.store import Store
from micros_tooling.storage.packages import require


def receipt(store):
    record = read_record(store) or {}
    running = daemon.running(store)
    status = daemon.request(store, {'action': 'status'}) if running else {}
    saved = store.metadata('runtime-state.json', {})
    controller = dict(state='running' if running else 'stopped',
                      startup_error=saved.get('error') if not running and saved.get('ready') is False else None)
    return dict(running=running, controller=controller, requested=store.selection()['enabled'],
                active=status.get('active', {}), last_good=record.get('good'),
                pending_candidate=record.get('candidate'),
                last_failure=store.metadata('last-failure.json', None),
                services=status.get('services', {}), store=str(store.root))


def shutdown(store):
    if not daemon.running(store):
        return
    daemon.request(store, {'action': 'shutdown'})
    deadline = time.monotonic() + 5
    while daemon.running(store):
        require(time.monotonic() < deadline, 'Host controller did not finish shutting down')
        time.sleep(0.02)


def main(arguments):
    parser = argparse.ArgumentParser(prog='micros host', description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for action in ('build', 'deploy', 'status', 'logs', 'stop', 'boot'):
        cmd = sub.add_parser(action)
        cmd.add_argument('--project', type=Path, default=Path('units/host.toml'))
        cmd.add_argument('--store', type=Path, help='persistent store; default: project/.micros/host')
        cmd.add_argument('--json', action='store_true', help='print structured output')
        if action in ('build', 'deploy'):
            cmd.add_argument('--output', type=Path, help='default: project/build/host-packages')
        if action in ('build', 'deploy', 'boot'):
            cmd.add_argument('--runtime', type=Path, help='existing micros-control; otherwise build the SDK host runtime')
    args = parser.parse_args(arguments)
    project = args.project.resolve()
    directory = host_directory(project)
    store = None if args.action == 'build' else Store(args.store or directory/'.micros/host')
    if args.action == 'logs':
        value = daemon.logs(store)
        if not value:
            diagnostic = daemon.logs(store, 'controller.log')
            if not diagnostic:
                diagnostic = store.metadata('runtime-state.json', {}).get('error', '')
            if diagnostic:
                value = 'Controller diagnostic (no runtime log):\n' + diagnostic
    elif args.action == 'stop':
        shutdown(store)
        value = receipt(store)
    elif args.action == 'status':
        value = receipt(store)
    else:
        from micros_tooling.host.build import build, runtime_binary
        runtime = args.runtime.resolve() if args.runtime else runtime_binary()
        if args.action in ('build', 'deploy'):
            packages = build(project, args.output or directory/'build/host-packages', runtime)
            if args.action == 'build':
                value = dict(packages=list(map(str, packages)))
            else:
                # Validate the complete graph before stopping the running application.
                with tempfile.TemporaryDirectory(prefix='micros-host-plan-') as temporary:
                    trial = Store(temporary)
                    selection = {}
                    from micros_tooling.storage.packages import read_package
                    for package in packages:
                        data = package.read_bytes()
                        trial.install(data)
                        manifest = read_package(data)['manifest']
                        selection[manifest['name']] = manifest['version']
                    trial.configure(selection)
                    trial.plan()
                for package in packages: store.install(package.read_bytes())
                print('Activating the complete host graph; running services will stop during replacement.', file=sys.stderr)
                shutdown(store)
                store.configure(selection)
                stage(store)
                daemon.boot(store, runtime)
                value = receipt(store)
                print(json.dumps(value, indent=2))
                require(value['active'] == selection, 'Host activation rolled back; see last_failure and last_good above. Requested configuration is retained.')
                return
        else:
            daemon.boot(store, runtime)
            value = receipt(store)
    print(json.dumps(value, indent=2) if args.json or not isinstance(value, str) else value)
