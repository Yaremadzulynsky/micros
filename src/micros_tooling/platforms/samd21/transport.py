"""Bounded USB management requests; never choose an ESP serial port."""
import json
import secrets
import time
import serial
from serial.tools import list_ports
from micros_tooling.storage.packages import require
from micros_tooling.platforms.embedded.telemetry import expand
from micros_tooling.platforms.embedded.transport import EmbeddedRemote


def find_port(port=None, serial_number=None):
    matches = [p for p in list_ports.comports() if p.vid in (0x2341, 0x2a03) and p.pid == 0x8054
               and (port is None or p.device == port) and (serial_number is None or p.serial_number == serial_number)]
    require(len(matches) == 1, 'Connect one MKR WiFi 1010 or select its exact --port and saved device identity')
    return matches[0]


class SerialRemote(EmbeddedRemote):
    platform='samd21';target=5;bank_sizes=(40960,65536)
    write_chunk = 64
    def __init__(self, port=None, serial_number=None):
        device = find_port(port, serial_number)
        self.session = secrets.token_hex(16)
        self.serial_number = device.serial_number
        self.port = device.device
        self.serial = serial.Serial(device.device, 115200, timeout=0.2, write_timeout=3, exclusive=True)



from micros_tooling.platforms.embedded.transport import NetworkRemote as EmbeddedNetworkRemote
class NetworkRemote(EmbeddedNetworkRemote):
    platform='samd21';target=5;bank_sizes=(40960,65536)
