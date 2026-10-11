"""Generate board wiring and service grants from application data."""

import hashlib
import json
import copy
from pathlib import Path

from micros_tooling.storage.packages import integer, require


def board_psram_bytes(board):
    return 2 * 1024 * 1024 if board and board["profile"] == "adafruit_feather_esp32_v2" else 0


def select_board(project, selected=None):
    """Use an explicit/saved definition, or the sole board next to an application."""
    from micros_tooling.config.configuration import read_toml
    project = Path(project).resolve()
    if project.suffix == ".toml" and "board" in read_toml(project):
        if selected is not None:
            require(load_board(selected) == load_board(project),
                    "Board override differs from the unit's embedded hardware definition")
        return project
    if selected is not None:
        path = Path(selected).resolve()
        require(path.is_file(), f"Board file not found: {path}")
        return path
    candidates = sorted((Path(project).resolve().parent / "boards").glob("*.toml"))
    require(len(candidates) <= 1, "Multiple board definitions available. Select --board PATH or a saved device with -d NAME.")
    return candidates[0] if candidates else None


def load_board(path, document=None):
    from micros_tooling.config.configuration import read_toml

    if path is None:
        return None
    data = copy.deepcopy(document) if document is not None else read_toml(path)
    if document is None:
        from micros_tooling.config.unit_model import contracts, gpio_directions
        gpio_directions(data, contracts(data, path))
    require("board" in data and data.keys() <= {"board", "unit", "project", "services", "channels", "management"},
            "Expected a board definition or complete unit configuration")
    board = copy.deepcopy(data["board"])
    require(isinstance(board, dict), "board must be a table")
    resources = board.get("gpio", {})
    require(isinstance(resources, dict), "board.gpio must be a table")
    services = data.get("services", {})
    require(isinstance(services, dict), "services must be a table")
    for alias, service in services.items():
        require(isinstance(service, dict), f"{alias}: service must be a table")
        if not service.get('enabled', True) and 'pins' in service:
            continue
        bindings = service.get("gpio_bindings", {})
        require(isinstance(bindings, dict), f"{alias}: gpio_bindings must be a table")
        for role, binding in bindings.items():
            if not isinstance(binding, dict):
                continue
            label = f"{alias}.gpio_bindings.{role}"
            require({"pin", "direction"} <= binding.keys() <= {"pin", "direction", "name", "pull"},
                    f"{label}: declare pin, direction, optional pull and resource name")
            name = binding.get("name", role)
            require(isinstance(name, str), f"{label}: name must be a string")
            require(name not in resources,
                    f"{label}: GPIO resource '{name}' is already declared; use a distinct name or reference the existing resource")
            resources[name] = {field: binding[field] for field in ("pin", "direction", "pull") if field in binding}
    if resources:
        board["gpio"] = resources
    return board_definition(board)


def board_definition(value):
    """Resolve stable logical lines by resource name, independently of TOML order."""
    from micros_tooling.config.configuration import valid_identifier

    if isinstance(value, dict) and value.get("profile") == "esp8266_4mb":
        from micros_tooling.platforms.esp8266.board import definition
        return definition(value)
    if isinstance(value, dict) and value.get("profile") == "arduino_mkr_wifi_1010":
        from micros_tooling.platforms.samd21.board import definition
        return definition(value)
    require(isinstance(value, dict) and value.keys() <= {"profile", "chip", "gpio", "recovery_button", "flash_mb"}, "Unknown board setting")
    if not value:
        return None
    require(isinstance(value.get("profile"), str) and valid_identifier(value["profile"]) and len(value["profile"]) <= 64, "board.profile is required (maximum 64 characters)")
    from micros_tooling.config.chips import board_capabilities, validate_gpio
    capabilities = board_capabilities(value["profile"], value.get("chip"))
    resources = value.get("gpio", {})
    require(isinstance(resources, dict) and len(resources) <= 4,
            "board.gpio supports zero to four resources for the current ESP32 runtime")
    flash_mb = value.get("flash_mb", 8)
    require(type(flash_mb) is int and flash_mb in (4, 8), "board.flash_mb must be 4 or 8")
    resolved = []
    pins = set()
    for line, (name, resource) in enumerate(sorted(resources.items())):
        require(valid_identifier(name) and len(name) <= 32, "Board GPIO names must be C identifiers")
        require(isinstance(resource, dict) and {"pin", "direction"} <= resource.keys() <= {"pin", "direction", "pull"},
                f"board.gpio.{name}: declare pin, direction and optional pull")
        pin = integer(resource["pin"], 0, 39, f"board.gpio.{name}.pin")
        # Original ESP32 silicon has gaps in its GPIO numbering; GPIO6..11 are
        # reserved for flash on the supported Feather profile.
        require(capabilities is not None or pin not in {6, 7, 8, 9, 10, 11, 24, 28, 29, 30, 31},
                f"board.gpio.{name}: unavailable or flash-reserved ESP32 pin")
        direction = resource["direction"]
        require(direction in ("input", "output"), f"board.gpio.{name}: direction must be input or output")
        require(direction == "input" or pin < 34, f"board.gpio.{name}: GPIO{pin} is input-only")
        pull = resource.get("pull", "none")
        if capabilities is not None:
            validate_gpio(capabilities, pin, direction, pull, f"board.gpio.{name}")
        else:
            require(pull == "none", f"board.gpio.{name}: pull capabilities are unknown for {value['profile']}")
        require(pin not in pins, f"board.gpio.{name}: GPIO{pin} is already assigned")
        pins.add(pin)
        resolved.append(dict(name=name, line=line, pin=pin, direction=direction))
    recovery = value.get("recovery_button")
    if recovery == "":
        recovery = None
    if recovery is not None:
        require(isinstance(recovery, str) and recovery in resources
                and resources[recovery]["direction"] == "input",
                "board.recovery_button must name an input GPIO resource")
    definition = dict(profile=value["profile"], gpio=resolved, recovery_button=recovery)
    # Preserve existing 8 MiB fingerprints; only the alternate layout adds identity data.
    if flash_mb != 8:
        definition["flash_mb"] = flash_mb
    definition["sha256"] = hashlib.sha256(json.dumps(definition, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return definition


def resource_header(name, gpio):
    """Expose named open operations only for resources granted to this service."""
    guard = f"MICROS_GENERATED_{name.upper()}_RESOURCES_H"
    lines = [f"/* Generated from {name} resource grants; edit micros.toml. */",
             f"#ifndef {guard}", f"#define {guard}", "#include <micros/service.h>"]
    for resource in gpio:
        resource_name = resource["name"]
        lines += [f"#define {name.upper()}_{resource_name.upper()}_GPIO_PIN {resource['pin']}u", f"/** @brief Open {resource_name}: GPIO{resource['pin']}, {resource['direction']}; close with gpio_close. */",
                  f"static inline micros_result_t {name}_{resource_name}_open(const micros_service_args_t *args, micros_handle_t *handle)",
                  "{", f"    return args->api->gpio_open(args->context, {resource['line']}u, handle);", "}"]
    lines += [f"#define {name.upper()}_GPIO_COUNT {len(gpio)}u",
              f"#define {name.upper()}_GPIO_PINS(X) " + " ".join(
                  f"X({index}, {name}_{r['name']}, {r['pin']}u, {int(r['direction'] == 'output')}u)"
                  for index, r in enumerate(gpio))]
    return "\n".join(lines + ["#endif", ""])


def board_header(board):
    """Emit physical base limits and the initial recovery fallback."""
    require(board is not None, "Base builds require a board definition; select --board PATH")
    recovery_pin = next((item["pin"] for item in board["gpio"] if item["name"] == board["recovery_button"]), -1)
    entries = ", ".join("{%d, %d}" % (item["pin"], item["direction"] == "output") for item in board["gpio"])
    return ("/* Generated from board configuration; edit micros.toml. */\n"
            "#ifndef MICROS_GENERATED_BOARD_H\n#define MICROS_GENERATED_BOARD_H\n"
            f'#define MICROS_BOARD_PROFILE {json.dumps(board["profile"])}\n'
            f'#define MICROS_BOARD_GPIO_NAMES {{ {", ".join(json.dumps(item["name"]) for item in board["gpio"]) or "NULL"} }}\n'
            f"#define MICROS_BOARD_FLASH_MB {board.get('flash_mb', 8)}u\n"
            f"#define MICROS_BOARD_GPIO_LINES {len(board['gpio'])}u\n"
            "#define MICROS_RUNTIME_GPIO_CAPACITY 4u\n"
            f"#define MICROS_BOARD_HAS_RECOVERY_BUTTON {int(recovery_pin >= 0)}\n"
            f"#define MICROS_BOARD_RECOVERY_GPIO {recovery_pin}\n"
            f'#define MICROS_BOARD_CONFIG_SHA256 "{board["sha256"]}"\n'
            # A dummy storage element avoids nonstandard zero-length C arrays;
            # GPIO_LINES remains zero, so it can never be opened or initialized.
            f"#define MICROS_BOARD_GPIO_INITIALIZERS {{ {entries or '{0, 0}'} }}\n#endif\n")


def verify_board_firmware(board, firmware):
    """Check physical compatibility; legacy bases additionally fix their pin mapping."""
    from elftools.elf.elffile import ELFFile

    if board is None:
        return
    with Path(firmware).open("rb") as stream:
        elf = ELFFile(stream)
        table = elf.get_section_by_name(".symtab")
        if table and table.get_symbol_by_name("micros_board_dynamic_bindings"):
            # Pin assignments are graph data on capable bases; chip/flash remain physical.
            symbols = table.get_symbol_by_name("micros_board_flash_mb")
            require(symbols, "Base has no physical flash identity")
            symbol=symbols[0]; section=elf.get_section(symbol["st_shndx"])
            offset=symbol["st_value"]-section["sh_addr"]
            require(int.from_bytes(section.data()[offset:offset+4],"little")==board.get("flash_mb",8),
                    "Board flash size differs from the physical base")
            return
        symbols = table.get_symbol_by_name("micros_board_config_sha256") if table else None
        require(symbols, "Paired base has no generated board definition. Prepare and physically migrate the base with micros init.")
        symbol = symbols[0]
        section = elf.get_section(symbol["st_shndx"])
        offset = symbol["st_value"] - section["sh_addr"]
        actual = section.data()[offset:offset + 65]
        require(actual == board["sha256"].encode() + b"\0",
                "Board configuration differs from the paired base. Restore its [board] settings or prepare and physically migrate the base.")


def firmware_gpio_count(firmware):
    """Read generated capacity, retaining the original two-line base contract for old ELFs."""
    from elftools.elf.elffile import ELFFile

    with Path(firmware).open("rb") as stream:
        elf = ELFFile(stream)
        table = elf.get_section_by_name(".symtab")
        symbols = table.get_symbol_by_name("micros_board_gpio_count") if table else None
        if not symbols:
            return 2  # Legacy Feather bases exposed only red LED and user button.
        symbol = symbols[0]
        section = elf.get_section(symbol["st_shndx"])
        offset = symbol["st_value"] - section["sh_addr"]
        count = int.from_bytes(section.data()[offset:offset + 4], "little")
        require(0 <= count <= 4, "Invalid base GPIO capacity")
        return count


def board_partitions(board, ota=False):
    """Keep base/NVS offsets stable; both layouts exceed the two 128 KiB service banks."""
    if ota:
        app_bytes = 0x180000 if board.get("flash_mb", 8) == 4 else 0x200000
        data = 0x20000 + 2 * app_bytes
        return ("# A/B base OTA v1. Install this layout physically before remote updates.\n"
                "nvs,data,nvs,0x9000,0x6000\nphy_init,data,phy,0xf000,0x1000\n"
                "otadata,data,ota,0x10000,0x2000\n"
                f"ota_0,app,ota_0,0x20000,0x{app_bytes:x}\n"
                f"ota_1,app,ota_1,0x{0x20000 + app_bytes:x},0x{app_bytes:x}\n"
                f"services,data,0x41,0x{data:x},0x40000\n"
                f"activation,data,0x40,0x{data + 0x40000:x},0x2000\n")
    service_bytes = 0x100000 if board.get("flash_mb", 8) == 4 else 0x400000
    return ("# Generated board flash layout; base updates require physical flashing.\n"
            "nvs,data,nvs,0x9000,0x6000\nphy_init,data,phy,0xf000,0x1000\n"
            "factory,app,factory,0x10000,0x180000\n"
            f"services,data,0x41,0x190000,0x{service_bytes:x}\n"
            f"activation,data,0x40,0x{0x190000 + service_bytes:x},0x2000\n")


def validate_bindings(bindings, target=2):
    """Validate the portable graph wiring payload carried by every service package."""
    if target == 6:
        from micros_tooling.platforms.esp8266.board import validate_bindings as validate_esp8266_bindings
        return validate_esp8266_bindings(bindings)
    if target == 5:
        from micros_tooling.platforms.samd21.board import validate_bindings as validate_arm_bindings
        return validate_arm_bindings(bindings)
    require(isinstance(bindings,dict) and bindings.keys()=={'gpio','recovery_button'}, 'Invalid board bindings')
    gpio=bindings['gpio']
    require(isinstance(gpio,list) and len(gpio)<=4,'At most four GPIO bindings are supported')
    resources={}
    for item in gpio:
        require(isinstance(item,dict) and item.keys()=={'name','line','pin','direction'},'Invalid GPIO binding')
        require(isinstance(item['name'],str) and item['name'] not in resources,'Duplicate GPIO name')
        require(item['pin'] not in (1,3),'GPIO1/3 are reserved for the resident serial controller')
        integer(item['line'], 0, 3, 'GPIO logical line')
        resources[item['name']]={key:item[key] for key in ('pin','direction')}
    resolved=board_definition(dict(profile='deployment',gpio=resources,recovery_button=bindings['recovery_button']))
    require(resolved['gpio']==gpio,'GPIO bindings must use canonical name order and logical IDs')
    return bindings
