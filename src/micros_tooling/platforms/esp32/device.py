"""Bounded serial transport and graph encoding for the Feather V2 local controller."""
from pathlib import Path
import struct
import time
import zlib
import serial
from micros_tooling.storage.packages import admission_plan, read_package, bounded_read, PACKAGE_LIMIT, PackageError, require
from micros_tooling.platforms.esp32.build_service import load_symbol_addresses

from micros_tooling.storage.deployment import GRAPH_MAGIC, GRAPH_BYTES, encode_graph
IMAGE_SLOTS = 4


def prepare(paths, firmware, bank, *, allow_archived_abi=False):
    """Encode a graph; archive mode is for read-only historical reconstruction only."""
    require(bank in (0, 1), 'bank must be zero or one')
    packages = [read_package(bounded_read(path, PACKAGE_LIMIT), allow_archived_abi=allow_archived_abi) for path in paths]
    plan = admission_plan(packages, target=2)
    from micros_tooling.config.resources import firmware_gpio_count
    gpio_count = firmware_gpio_count(firmware)
    require(all(service['permissions']['gpio_mask'] < (1 << gpio_count) for service in plan['services']),
            'GPIO grant exceeds the paired base board definition')
    symbols = load_symbol_addresses(Path(firmware))
    bindings = packages[0]['manifest'].get('board_bindings', dict(gpio=[], recovery_button=None))
    require(all(package['manifest'].get('board_bindings', dict(gpio=[], recovery_button=None)) == bindings for package in packages),
            'All services must use the same board wiring definition')
    plan['board_bindings'] = bindings
    images = {}
    by_name = {package['manifest']['name']: package for package in packages}
    slots_by_name = {}
    # Load all images before hooks and start subscribers before publishers.
    ordered = sorted(plan['services'], key=lambda service: (bool(service['permissions']['publish_mask']), service['name']))
    for service in ordered:
        package = by_name[service['name']]
        metadata = package['metadata']
        slots = [slot for slot in range(IMAGE_SLOTS) if
                 metadata['code_base'] == symbols[f'micros_code_slot{slot}'] and
                 metadata['data_base'] == symbols[f'micros_data_slot{slot}']]
        require(len(slots) == 1 and slots[0] not in images, 'image slot/base mismatch or conflict')
        slot = slots[0]
        require(metadata.get('rodata_base', 0) == symbols.get(f'micros_rodata_slot{slot}', 0),
                'image constant mapping differs from paired base')
        require(metadata['code_bytes'] <= symbols.get('micros_service_code_capacity', 8192), 'Image exceeds base code capacity')
        require(metadata['data_bytes'] + metadata['bss_bytes'] <= symbols.get('micros_service_data_capacity', 4096),
                'image exceeds paired base writable slot')
        images[slot] = package['image']
        slots_by_name[service['name']] = slot
    graph = encode_graph(plan, bank, slots_by_name, bindings)
    return images, graph, plan


class Device:
    """One local controller session; uses an idempotent handshake across USB-adapter reset on open."""
    def __init__(self, port, transcript=None):
        self.serial = serial.Serial(port=None, baudrate=115200, timeout=0.2, write_timeout=15)
        self.serial.dtr = False
        self.serial.rts = False
        self.serial.port = port
        self.serial.open()
        self.transcript = transcript
        # The CH9102F can reset on open despite inactive DTR/RTS. INFO is safe
        # to retry; first-use formatting of the 4 MiB partition can take 90 s.
        for attempt in range(120):
            try:
                self.command('INFO', 'END STATUS', timeout=1)
                break
            except TimeoutError:
                if attempt == 119:
                    self.close()
                    raise
            except PackageError as error:
                # A migrated base may reject the old selected graph while its
                # USB adapter resets on open. This boot diagnostic is not a
                # rejection of INFO; retry the idempotent handshake.
                if str(error) != 'REJECT selected bank integrity' or attempt == 119:
                    self.close()
                    raise

    def close(self):
        self.serial.close()

    def line(self):
        line = self.serial.readline().decode('utf-8', errors='replace').strip()
        if line and self.transcript:
            self.transcript.write(line + '\n'); self.transcript.flush()
        return line

    def expect(self, prefix, timeout=20):
        deadline = time.monotonic() + timeout
        observed = []
        while time.monotonic() < deadline:
            line = self.line()
            if line:
                observed.append(line)
                if line.startswith(prefix):
                    require(not line.startswith(('REJECT', 'IMAGE REJECT', 'CONFIG REJECT', 'BOOT REJECT')), line)
                    return observed
                require(not line.startswith(('REJECT', 'IMAGE REJECT', 'CONFIG REJECT', 'BOOT REJECT')), line)
        raise TimeoutError(f'expected {prefix}; last lines: {observed[-8:]}')

    def command(self, command, prefix, timeout=20):
        self.serial.write((command + '\n').encode())
        return self.expect(prefix, timeout)

    def status(self):
        return self.command('STATUS', 'END STATUS')

    def upload(self, images, graph, bank):
        self.command('STOP', 'STOPPED OK')
        for slot, image in sorted(images.items()):
            self.command(f'IMAGE {bank} {slot} {len(image)}', 'READY')
            self.serial.write(image)
            self.expect('IMAGE OK')
        self.command(f'CONFIG {bank} {len(graph)}', 'READY')
        self.serial.write(graph)
        self.expect('CONFIG OK')
        self.command(f'BOOT {bank}', 'BOOT OK')
        if any('pending=1' in line for line in self.status()):
            self.expect('HEALTH COMMITTED', timeout=15)
