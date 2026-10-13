"""ESP8266 serial selection; never reset an ESP32 or select an Arduino port."""

import secrets, serial, time
from serial.tools import list_ports
from micros_tooling.storage.packages import require
from micros_tooling.platforms.embedded.transport import EmbeddedRemote


def find_port(port=None, serial_number=None):
    ports = [
        p
        for p in list_ports.comports()
        if p.vid in (0x10C4, 0x1A86)
        and (not port or p.device == port)
        and (not serial_number or p.serial_number == serial_number)
    ]
    devices = {}
    for p in sorted(ports, key=lambda p: ("SLAB" in p.device, p.device)):
        devices.setdefault((p.vid, p.pid, p.serial_number, p.location), p)
    require(len(devices) == 1, "Select one ESP8266 serial bridge with --port")
    return next(iter(devices.values()))


class SerialRemote(EmbeddedRemote):
    platform = "esp8266"
    target = 6
    bank_sizes = (131072,)

    def __init__(self, port=None, serial_number=None):
        p = find_port(port, serial_number)
        self.session = secrets.token_hex(16)
        self.serial_number = p.serial_number
        self.port = p.device
        self.serial = serial.Serial(None, 115200, timeout=0.2, write_timeout=3, exclusive=True)
        self.serial.dtr = False
        self.serial.rts = False
        self.serial.port = p.device
        self.serial.open()
        time.sleep(3)
        self.serial.reset_input_buffer()


from micros_tooling.platforms.embedded.transport import NetworkRemote as PlatformNetworkRemote


class NetworkRemote(PlatformNetworkRemote):
    platform = "esp8266"
    target = 6
    bank_sizes = (131072,)
