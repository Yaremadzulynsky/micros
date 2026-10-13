"""Collect diagnostic evidence through the existing shared server stream leases."""
import argparse
import json
import os
from pathlib import Path
import time

from micros_tooling.fleet.server import configured_remote, choose_device
from micros_tooling.storage.workspace import Workspace
from micros_tooling.storage.packages import require

ROOT = Path(__file__).resolve().parents[3]


def connect_device(workspace, requested):
    remote = configured_remote(workspace)
    require(remote is not None, 'A configured micros server is required')
    devices = json.loads(remote.raw('GET', '/v1/devices'))['devices']
    remote.device_id = choose_device(devices, requested)['device_id']
    return remote


def stream(remote, payload):
    return json.loads(remote.raw('POST', '/v1/streams/' + remote.device_id, json.dumps(payload).encode()))


def open_stream(remote, service, port):
    status = remote.status()
    require(status.get('identity', {}).get('device_id') == remote.device_id, 'Device identity mismatch')
    opened = stream(remote, dict(action='open', base=status['identity']['base_sha256'],
                               graph=status['activation']['good_sha256'], service=service, port=port))
    return opened, dict(device_id=remote.device_id, base_sha256=status['identity']['base_sha256'],
                        graph_sha256=status['activation']['good_sha256'],
                        activation_sequence=status['activation']['sequence'], service=service, port=port)


def collect(remote, service, port, output, *, seconds=15, max_events=1024, clock=time.monotonic):
    require(type(seconds) in (int, float) and 0 < seconds <= 600, 'Capture duration must be 0..600 seconds')
    require(type(max_events) is int and 1 <= max_events <= 10000, 'Capture limit must be 1..10000 events')
    # Reserve the file before opening a remote lease; never truncate prior evidence.
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as target:
        opened = None
        samples = gaps = events = 0
        outcome = 'duration'
        try:
            opened, provenance = open_stream(remote, service, port)
            target.write(json.dumps(dict(kind='provenance', **provenance)) + '\n')
            deadline = clock() + seconds
            cursor = opened['cursor']
            while clock() < deadline and events < max_events:
                reply = stream(remote, dict(action='read', reader=opened['reader'], cursor=cursor))
                cursor = reply['cursor']
                for event in reply['events']:
                    if events == max_events: break
                    target.write(json.dumps(dict(kind='event', **event)) + '\n')
                    events += 1
                    samples += event.get('state') == 'sample'
                    gaps += event.get('state') == 'gap'
                target.flush()
            if events == max_events: outcome = 'event_limit'
        except BaseException:
            outcome = 'interrupted'
            raise
        finally:
            target.write(json.dumps(dict(kind='capture_end', outcome=outcome, samples=samples, gap_events=gaps)) + '\n')
            if opened:
                try: stream(remote, dict(action='close', reader=opened['reader']))
                except Exception:
                    target.write(json.dumps(dict(kind='cleanup', lease_closed=False, expires_after_seconds=30)) + '\n')
    return dict(output=str(output), outcome=outcome, samples=samples, gap_events=gaps)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', required=True)
    parser.add_argument('--service', required=True, help='Deployed service name, e.g. diagnostic.channel-probe')
    parser.add_argument('--port', required=True, help='report, records, or status as declared by the service')
    parser.add_argument('--seconds', type=float, default=15)
    parser.add_argument('--max-events', type=int, default=1024)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    remote = connect_device(Workspace(Path(os.environ.get('MICROS_STATE_DIR', ROOT / '.micros'))), args.device)
    print(json.dumps(collect(remote, args.service, args.port, args.output, seconds=args.seconds, max_events=args.max_events)))


if __name__ == '__main__':
    main()
