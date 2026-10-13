#!/usr/bin/env python3
"""Deploy the portable demo and exercise MKR lifecycle and durable bank selection."""
import argparse
import json
from pathlib import Path
import sys
import time
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from micros_tooling.platforms.samd21.build import build
from micros_tooling.platforms.samd21.transport import SerialRemote
from micros_tooling.platforms.samd21.cli import wait_confirmed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--serial-number', required=True)
    parser.add_argument('--firmware', type=Path, required=True)
    parser.add_argument('--compiler-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/samd21/hardware-test.json')
    args = parser.parse_args()
    project = ROOT / 'examples/mkr-demo/micros.toml'
    evidence = []
    with SerialRemote(args.port, args.serial_number) as remote:
        def running():
            deadline = time.monotonic() + 3
            while True:
                status = remote.status()
                if status['services'] and all(s['state'] == 4 for s in status['services']):
                    break
                if time.monotonic() >= deadline:
                    break
                time.sleep(.05)
            assert len(status['services']) == 3 and all(s['state'] == 4 and s['result'] == 0 for s in status['services']), status
            assert not status['pending'] and status['good'] == status['active'], status
            evidence.append(status)
            return status
        for _ in range(2):
            status = remote.status()
            bank = 1 - status['good'] if status['good'] < 2 else 0
            output = ROOT / 'build/samd21/hardware-test' / str(bank)
            report = build(project, args.firmware, output, args.compiler_dir, bank, project)
            remote.deploy((output / 'bank.bin').read_bytes(), report)
            running()
        previous = remote.status()['previous']
        remote.request('ROLLBACK')
        wait_confirmed(remote, previous)
        running()
        levels = set()
        for _ in range(12):
            levels.update(remote.status()['gpio'])
            time.sleep(.1)
        assert levels == {0, 1}, levels
        remote.request('LOGS')
        time.sleep(1.2)
        assert 'Hello world' in bytes.fromhex(remote.request('LOGS')['hex']).decode()
        for _ in range(5):
            remote.request('STOP')
            assert remote.status()['services'] == []
            remote.request('RECOVER')
            running()
        assert len({s['heap_headroom'] for s in evidence[-5:]}) == 1, evidence[-5:]
        # A partially written bank must never displace the known-good graph.
        good = running()['good']
        remote.request('BEGIN ' + str(1 - good))
        remote.request('WRITE 0 ' + ('00' * 64))
        assert remote.request('ACTIVATE', allow_error=True)['result'] != 0
        assert running()['good'] == good
        remote.request('REBOOT')
    deadline = time.monotonic() + 20
    while True:
        try:
            with SerialRemote(serial_number=args.serial_number) as remote:
                status = remote.status()
                assert status['good'] == good and len(status['services']) == 3, status
                evidence.append(status)
                break
        except (OSError, ValueError, TimeoutError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(.5)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + '\n')
    print('PASS: two deployments, rollback, GPIO, timer logs, five lifecycle cycles, rejected partial bank, reboot persistence')


if __name__ == '__main__':
    main()
