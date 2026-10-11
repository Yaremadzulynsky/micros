"""Platform registration: native IDs, starter board and command provider.

Add one entry here when a new firmware backend and its SDK tooling are ready.
Hardware facts remain in config/chips and config/boards; they are not protocol choices.
"""
from dataclasses import dataclass
from importlib import import_module

@dataclass(frozen=True)
class Platform:
    name: str
    native_ids: tuple
    board: str | None = None
    provider: str | None = None
    starter_stack: int | None = None

PLATFORMS = (
    Platform('posix', (1, 3, 4)),
    Platform('esp32', (2,), 'adafruit_feather_esp32_v2'),
    Platform('esp8266', (6,), 'esp8266_4mb', 'micros_tooling.platforms.esp8266.cli'),
    Platform('samd21', (5,), 'arduino_mkr_wifi_1010', 'micros_tooling.platforms.samd21.cli', 1024),
)

def get(name):
    return next((platform for platform in PLATFORMS if platform.name == name), None)

def hardware_names():
    return [platform.name for platform in PLATFORMS if platform.board]

def supports_identity(name, native_id):
    platform = get(name)
    return platform is not None and native_id in platform.native_ids

def handler_for(args):
    selected = getattr(args, 'platform', None)
    if selected:
        platform = get(selected)
        if platform is None: raise ValueError('Unknown platform: ' + selected)
        return import_module(platform.provider).main if platform.provider else None
    for platform in PLATFORMS:
        if platform.provider:
            provider = import_module(platform.provider)
            if provider.handles(args): return provider.main
    return None
