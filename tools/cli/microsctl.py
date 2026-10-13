#!/usr/bin/env python3
"""Local package, admission, and lifecycle commands for micros."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from micros_tooling.storage.packages import PackageError, admission_plan, build_package, canonical_json, read_json, read_package, require, bounded_read, PACKAGE_LIMIT, MANIFEST_LIMIT, IMAGE_LIMIT, SCHEMA_LIMIT
from micros_tooling.storage.store import Store
from micros_tooling.host import daemon


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, default=Path('build/store'))
    commands = parser.add_subparsers(dest='command', required=True)
    pack = commands.add_parser('package')
    pack.add_argument('manifest', type=Path); pack.add_argument('image', type=Path); pack.add_argument('output', type=Path)
    pack.add_argument('--schema', action='append', default=[], metavar='NAME=PATH')
    inspect = commands.add_parser('inspect'); inspect.add_argument('package', type=Path)
    install = commands.add_parser('install'); install.add_argument('package', type=Path)
    commands.add_parser('list'); commands.add_parser('plan'); commands.add_parser('status'); commands.add_parser('logs')
    configure = commands.add_parser('configure'); configure.add_argument('selection', type=Path)
    enable = commands.add_parser('enable'); enable.add_argument('name'); enable.add_argument('version')
    disable = commands.add_parser('disable'); disable.add_argument('name')
    for operation in ('start', 'stop', 'restart'):
        command = commands.add_parser(operation); command.add_argument('name')
    commands.add_parser('shutdown')
    for operation in ('boot', 'activate', '_serve'):
        command = commands.add_parser(operation); command.add_argument('--runtime', type=Path, default=Path('build/host/micros-control'))
    args = parser.parse_args()
    store = Store(args.store)
    if args.command == 'package':
        schemas = {}
        for item in args.schema:
            name, path = item.split('=', 1)
            require(name not in schemas, f'duplicate schema {name}')
            schemas[name] = bounded_read(path, SCHEMA_LIMIT)
        args.output.write_bytes(build_package(read_json(bounded_read(args.manifest, MANIFEST_LIMIT)), bounded_read(args.image, IMAGE_LIMIT), schemas))
        return {'package': str(args.output)}
    if args.command == 'inspect':
        package = read_package(bounded_read(args.package, PACKAGE_LIMIT))
        return {'manifest': package['manifest'], 'metadata': package['metadata'], 'sha256': package['sha256']}
    if args.command == 'install': return store.install(bounded_read(args.package, PACKAGE_LIMIT))
    if args.command == 'list': return {'installed': store.index()['services'], 'enabled': store.selection()['enabled']}
    if args.command == 'plan': return store.plan()
    if args.command in ('configure', 'enable', 'disable'):
        require(not daemon.running(store), 'shutdown the runtime before changing the boot selection')
        enabled = store.selection()['enabled']
        if args.command == 'configure': enabled = read_json(bounded_read(args.selection, MANIFEST_LIMIT))
        elif args.command == 'enable': enabled[args.name] = args.version
        else:
            require(args.name in enabled, f'{args.name}: not enabled'); del enabled[args.name]
        return store.configure(enabled)
    if args.command == 'activate':
        require(not daemon.running(store), 'shutdown the runtime before activation')
        from micros_tooling.host.activation import stage
        stage(store)
        return daemon.boot(store, args.runtime)
    if args.command == 'boot': return daemon.boot(store, args.runtime)
    if args.command == '_serve': daemon.serve(args.store, args.runtime); return None
    if args.command == 'logs': return daemon.logs(store)
    return daemon.request(store, {'action': args.command, **({'name': args.name} if hasattr(args, 'name') else {})})


if __name__ == '__main__':
    try:
        value = main()
        if value is not None: print(json.dumps(value, indent=2, sort_keys=True))
    except (PackageError, OSError, ValueError, KeyError) as error:
        print(f'ERROR {error}', file=sys.stderr)
        raise SystemExit(1)
