"""ESP8266 pin validation, isolated from the existing board implementations."""

import hashlib
import json
from micros_tooling.storage.packages import require, integer


def definition(value):
    from micros_tooling.config.configuration import valid_identifier

    require(
        isinstance(value, dict) and value.keys() <= {"profile", "gpio", "recovery_button"},
        "Unknown ESP8266 board setting",
    )
    require(value.get("profile") == "esp8266_4mb", "Expected ESP8266 4 MiB profile")
    resources = value.get("gpio", {})
    require(
        isinstance(resources, dict) and len(resources) <= 4,
        "ESP8266 supports at most four named GPIO resources",
    )
    gpio, pins = [], set()
    for line, (name, item) in enumerate(sorted(resources.items())):
        require(valid_identifier(name) and len(name) <= 32, "Invalid GPIO name")
        require(
            isinstance(item, dict) and item.keys() == {"pin", "direction"},
            "GPIO requires pin and direction",
        )
        pin = integer(item["pin"], 0, 16, "ESP8266 GPIO number")
        require(pin not in (1, 3, 6, 7, 8, 9, 10, 11), "Pin is reserved for UART or flash")
        require(
            pin not in pins and item["direction"] in ("input", "output"),
            "Duplicate pin or invalid direction",
        )
        pins.add(pin)
        gpio.append(dict(name=name, line=line, pin=pin, direction=item["direction"]))
    recovery = value.get("recovery_button") or None
    require(
        recovery is None,
        "ESP8266 ROM recovery uses the programmer; recovery-button bindings are not implemented",
    )
    result = dict(profile="esp8266_4mb", gpio=gpio, recovery_button=None, flash_bytes=4194304)
    result["sha256"] = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return result


def validate_bindings(value):
    require(
        isinstance(value, dict) and value.keys() == {"gpio", "recovery_button"},
        "Invalid ESP8266 bindings",
    )
    require(isinstance(value["gpio"], list), "Invalid GPIO list")
    resources = {}
    for item in value["gpio"]:
        require(
            isinstance(item, dict) and item.keys() == {"name", "line", "pin", "direction"},
            "Invalid GPIO record",
        )
        require(item["name"] not in resources, "Duplicate GPIO name")
        resources[item["name"]] = dict(pin=item["pin"], direction=item["direction"])
    resolved = definition(
        dict(profile="esp8266_4mb", gpio=resources, recovery_button=value["recovery_button"])
    )
    require(resolved["gpio"] == value["gpio"], "GPIO bindings must be in canonical order")
    return value
