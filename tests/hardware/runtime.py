#!/usr/bin/env python3
"""Exercise the already flashed full runtime; deploys independent images over serial."""
import argparse
import json
from pathlib import Path
import re
import statistics
import struct
import sys
import time
import zlib
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from micros_tooling.platforms.esp32.device import Device, prepare
from micros_tooling.storage.packages import PackageError

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port', required=True)
parser.add_argument('--firmware', type=Path, default=Path('build/esp32-runtime/micros_runtime.elf'))
parser.add_argument('--packages', type=Path, default=Path('build/device-demo'))
parser.add_argument('--output', type=Path, default=Path('build/m5-hardware'))
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
images, graph, plan = prepare([args.packages / (name + '.msp') for name in ('button', 'logger', 'led')], args.firmware, 0)
with (args.output / 'transcript.log').open('w') as transcript:
    device = Device(args.port, transcript)
    try:
        device.upload(images, graph, 0)
        stopped_heaps, running = [], []
        # Two warm-up cycles allow IDF/newlib lazy bookkeeping to settle;
        # three further cycles must return to exactly the same measured baseline.
        for cycle in range(5):
            if cycle: device.command('BOOT 0', 'BOOT OK')
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline: device.line()
            status = device.status()
            assert sum('state=Running result=0' in line for line in status) == 3, status
            running.append(status)
            device.command('STOP', 'STOPPED OK')
            status = device.status()
            assert any('services=0' in line for line in status), status
            stopped_heaps.append(int(re.search(r' heap=(\d+)', '\n'.join(status)).group(1)))
        assert len(set(stopped_heaps[2:])) == 1, stopped_heaps
        # Corrupt data must fail without replacing the admitted file.
        damaged = bytearray(images[0]); damaged[-1] ^= 1
        device.command(f'IMAGE 0 0 {len(damaged)}', 'READY')
        device.serial.write(damaged)
        try: device.expect('IMAGE')
        except PackageError: pass
        else: raise AssertionError('corrupt image accepted')
        # Service record starts after 5 header + 16 channel words; duplicate slot.
        damaged_graph = bytearray(graph)
        struct.pack_into('<I', damaged_graph, (5 + 16 + 9) * 4,
                         struct.unpack_from('<I', graph, (5 + 16) * 4)[0])
        struct.pack_into('<I', damaged_graph, len(graph)-4, zlib.crc32(damaged_graph[:-4]))
        device.command(f'CONFIG 0 {len(graph)}', 'READY'); device.serial.write(damaged_graph)
        try: device.expect('CONFIG')
        except PackageError: pass
        else: raise AssertionError('conflicting slots accepted')
        device.command('BOOT 0', 'BOOT OK')
        device.command('REBOOT', 'REBOOTING')
        device.expect('AUTOBOOT OK')
        assert sum('state=Running result=0' in line for line in device.status()) == 3
    finally:
        device.close()
text = (args.output / 'transcript.log').read_text()
latencies = list(map(int, re.findall(r'LATENCY_US=(\d+)', text)))
assert len(latencies) >= 100, len(latencies)
assert 'LED level=1 verified' in text and 'LED level=0 verified' in text
report = dict(cycles=5, warmup_cycles=2, stopped_heaps=stopped_heaps, running=running,
              latency_samples=len(latencies), latency_min_us=min(latencies),
              latency_median_us=statistics.median(latencies), latency_max_us=max(latencies),
              plan=plan, corruption_rejected=True, slot_conflict_rejected=True, reboot_reconstructed=True)
(args.output / 'report.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
