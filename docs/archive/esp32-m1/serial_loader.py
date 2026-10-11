#!/usr/bin/env python3
"""M1 development transfer: RAM-only service upload and two lifecycle cycles."""
import argparse
from pathlib import Path
import time
import serial

# Match the baud that completed M1 flash/transfer testing without corruption.
SERIAL_BAUD = 115200
# A short per-read timeout allows the outer response deadline to be checked;
# the write deadline leaves ample margin for a 256-byte chunk at this baud.
SERIAL_READ_TIMEOUT_SECONDS = 0.2
SERIAL_WRITE_TIMEOUT_SECONDS = 5
# Allow boot/reset and command-response latency on this development adapter.
RESPONSE_TIMEOUT_SECONDS = 8
BOOT_HANDSHAKE_ATTEMPTS = 8
BOOT_ATTEMPT_TIMEOUT_SECONDS = 1
# Small chunks avoid USB adapter buffering dependence; the MCU still bounds
# the complete image using its announced length and staging capacity.
TRANSFER_CHUNK_BYTES = 256
# Two full lifecycle cycles plus serial output should fit comfortably in 10 s.
RUN_TIMEOUT_SECONDS = 10
EXPECTED_CYCLES = 2

def connect(port):
    device = serial.Serial(port=None, baudrate=SERIAL_BAUD, timeout=SERIAL_READ_TIMEOUT_SECONDS,
                           write_timeout=SERIAL_WRITE_TIMEOUT_SECONDS)
    device.dtr = False
    device.rts = False
    device.port = port
    device.open()
    return device

def read_until(device, prefixes, timeout=RESPONSE_TIMEOUT_SECONDS):
    deadline_seconds = time.monotonic() + timeout
    response_lines = []
    while time.monotonic() < deadline_seconds:
        response_line = device.readline().decode('utf-8', errors='replace').strip()
        if response_line:
            response_lines.append(response_line)
            if response_line.startswith(tuple(prefixes)):
                return '\n'.join(response_lines) + '\n'
    raise TimeoutError('Serial response timed out: ' + '\n'.join(response_lines))

def info(device):
    # Opening some USB adapters resets the board. Retry the idempotent INFO
    # handshake while the bootloader hands UART ownership to the application.
    last_error = None
    for _ in range(BOOT_HANDSHAKE_ATTEMPTS):
        device.write(b'INFO\n')
        try:
            return read_until(device, ['INFO '], timeout=BOOT_ATTEMPT_TIMEOUT_SECONDS)
        except TimeoutError as error:
            last_error = error
    raise last_error

def upload(device, payload):
    device.write(f'LOAD {len(payload)}\n'.encode())
    ready_response = read_until(device, ['READY ', 'REJECT '])
    if 'REJECT ' in ready_response:
        return ready_response
    # Small chunks avoid depending on the USB adapter's buffering capacity.
    for chunk_offset in range(0, len(payload), TRANSFER_CHUNK_BYTES):
        device.write(payload[chunk_offset:chunk_offset + TRANSFER_CHUNK_BYTES])
        device.flush()
    return read_until(device, ['LOADED', 'REJECT '])

def run(device):
    device.write(b'RUN\n')
    return read_until(device, ['DONE', 'REJECT ', 'FATAL '], timeout=RUN_TIMEOUT_SECONDS)
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('image', type=Path, nargs='?')
    arguments = parser.parse_args()
    with connect(arguments.port) as device:
        print(info(device), end='')
        if arguments.image:
            response = upload(device, arguments.image.read_bytes())
            print(response, end='')
            if 'LOADED' not in response:
                raise SystemExit(1)
            response = run(device)
            print(response, end='')
            if 'DONE' not in response or response.count('result=0') != EXPECTED_CYCLES:
                raise SystemExit(1)
