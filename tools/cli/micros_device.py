#!/usr/bin/env python3
"""Local service deployment/status on the Feather V2 serial console."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from micros_tooling.platforms.esp32.device import Device, prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--firmware', type=Path, default=Path('build/esp32-runtime/micros_runtime.elf'))
    parser.add_argument('--bank', type=int, choices=[0, 1], default=0)
    parser.add_argument('action', choices=['deploy', 'status', 'stop', 'reboot', 'boot'])
    parser.add_argument('packages', nargs='*', type=Path)
    args = parser.parse_args()
    prepared = prepare(args.packages, args.firmware, args.bank) if args.action == 'deploy' else None
    device = Device(args.port, sys.stdout)
    try:
        if prepared:
            images, graph, _ = prepared
            device.upload(images, graph, args.bank)
            device.status()
        elif args.action == 'status': device.status()
        elif args.action == 'stop': device.command('STOP', 'STOPPED OK')
        elif args.action == 'reboot': device.command('REBOOT', 'REBOOTING')
        else: device.command(f'BOOT {args.bank}', 'BOOT OK')
    finally:
        device.close()


if __name__ == '__main__':
    main()
