#!/usr/bin/env python3
"""Regression for controller hashing starving live service deadlines on the MKR."""
import argparse
import json
from pathlib import Path
import sys
import time
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from micros_tooling.platforms.samd21.build import build
from micros_tooling.platforms.samd21.transport import SerialRemote


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--serial-number', required=True)
    parser.add_argument('--firmware', type=Path, required=True)
    parser.add_argument('--compiler-dir', type=Path, required=True)
    parser.add_argument('--cycles', type=int, default=100)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/samd21/ipc-stress.json')
    args = parser.parse_args()
    project = ROOT / 'examples/mkr-ipc/micros.toml'
    output = ROOT / 'build/samd21/ipc-stress'
    records = []
    with SerialRemote(args.port, args.serial_number) as remote:
        status = remote.status()
        bank = 1 - status['good'] if status['good'] < 2 else 0
        report = build(project, args.firmware, output, args.compiler_dir, bank, project)
        remote.deploy((output / 'bank.bin').read_bytes(), report)
        wifi_before = remote.request('WIFI')
        for _ in range(args.cycles):
            # Deliberately recover while workers are still running. STOP first
            # would hide the priority/starvation bug this test is meant to catch.
            remote.request('RECOVER')
            time.sleep(.15)
            status = remote.status()
            assert len(status['services']) == 2 and all(s['state'] == 4 and s['result'] == 0 for s in status['services']), status
            assert status['good'] == bank and not status['pending'], status
            records.append(status)
        assert len({s['heap_headroom'] for s in records[1:]}) == 1, records
        logs = ''.join(bytes.fromhex(remote.request('LOGS')['hex']).decode() for _ in range(4))
        assert 'LATENCY_US=' in logs, logs
        wifi_after = remote.request('WIFI')
        assert not wifi_before['connected'] or wifi_after['connected'], wifi_after
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dict(statuses=records, wifi=wifi_after), indent=2) + '\n')
    print(f'PASS: {args.cycles} live IPC restarts, protobuf delivery, stable heap and Wi-Fi state')


if __name__ == '__main__':
    main()
