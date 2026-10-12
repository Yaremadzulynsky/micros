"""Offline chip capabilities, board connections and runtime restrictions."""
import copy
from pathlib import Path

from micros_tooling.config.configuration import read_toml, valid_identifier
from micros_tooling.storage.packages import require

CONFIG = Path(__file__).resolve().parents[3] / "config"


def load_chip(name):
    require(valid_identifier(name), "Invalid chip identifier")
    path = CONFIG / "chips" / (name + ".toml")
    require(path.is_file(), f"Unknown chip capabilities: {name}")
    data = read_toml(path)
    require(data["chip"]["id"] == name, "Chip capability identity mismatch")
    pins = {}
    for group in data["gpio"]["groups"].values():
        require(set(group) == {"pins", "input", "output", "pulls"}, "Invalid GPIO capability group")
        require(type(group["input"]) is bool and type(group["output"]) is bool,
                "GPIO directions must be boolean")
        require(isinstance(group["pulls"], list) and "none" in group["pulls"]
                and set(group["pulls"]) <= {"none", "up", "down"}, "Invalid GPIO pulls")
        for pin in group["pins"]:
            require(type(pin) is int and 0 <= pin <= 255 and pin not in pins, "Duplicate or invalid chip GPIO")
            pins[pin] = {key: copy.deepcopy(group[key]) for key in ("input", "output", "pulls")}
    for pin, fixed in data["gpio"].get("pins", {}).items():
        require(pin.isdecimal() and int(pin) in pins and set(fixed) <= {"adc"}, "Invalid fixed GPIO mapping")
        pins[int(pin)].update(copy.deepcopy(fixed))
    return dict(chip=data["chip"], peripherals=data["peripherals"], pins=pins)


def board_capabilities(profile, chip=None):
    require(valid_identifier(profile), "Invalid board profile")
    path = CONFIG / "boards" / (profile + ".toml")
    if not path.is_file():
        require(chip is None, f"Unknown board capabilities for {profile}; cannot verify chip {chip}")
        return None
    board = read_toml(path)
    require(board["board"]["profile"] == profile, "Board capability identity mismatch")
    selected = board["board"]["chip"]
    require(chip is None or chip == selected, f"{profile} requires chip {selected}, not {chip}")
    capabilities = load_chip(selected)
    connections = board.get("gpio", {})
    if any("chip_pin" in connection for connection in connections.values()):
        mapped, used = {}, set()
        for number, connection in connections.items():
            pin = connection.get("chip_pin")
            require(number.isdecimal() and 0 <= int(number) <= 255 and int(number) not in mapped,
                    "Invalid board pin number")
            require(type(pin) is int and pin in capabilities["pins"] and pin not in used,
                    "Missing, duplicate or unknown chip pin in board mapping")
            used.add(pin)
            mapped[int(number)] = dict(capabilities["pins"][pin], chip_pin=pin)
        capabilities["pins"] = mapped
    for key in ("exposed", "onboard"):
        require(all(type(pin) is int and pin in capabilities["pins"] for pin in board["board"][key]),
                f"Unknown pin in board {key} connections")
    require(all(type(pin) is int and pin in capabilities["pins"] for pin in board["runtime"]["reserved"]),
            "Unknown reserved board pin")
    return dict(**capabilities, board=board["board"], runtime=board["runtime"],
                connections=connections)


def validate_gpio(capabilities, pin, direction, pull, context):
    require(pull in ("none", "up", "down"), f'{context}: pull must be "none", "up", or "down"')
    info = capabilities["pins"].get(pin)
    require(info is not None, f"{context}: GPIO{pin} does not exist on {capabilities['chip']['id']}")
    require(info.get(direction, False), f"{context}: GPIO{pin} is input-only; {direction} is unsupported")
    require(pull in info["pulls"], f"{context}: GPIO{pin} does not support internal pull = {pull!r}; use none and an external resistor, or another pin")
    board, runtime = capabilities["board"], capabilities["runtime"]
    require(pin not in runtime["reserved"], f"{context}: GPIO{pin}: {runtime['reserved_reason']}")
    require(pin in board["exposed"] or pin in board["onboard"],
            f"{context}: GPIO{pin} is not a verified exposed or onboard connection on {board['profile']}")
    # Never accept a setting which current graph encoding would silently discard.
    require(pull == "none" or runtime["configurable_pulls"],
            f"{context}: GPIO{pin} supports {pull} in hardware, but configurable internal pulls are not yet supported by the micros runtime")


def resolve_pin_type(board, pin, kind, context):
    """Resolve the service's electrical requirement from board and chip facts."""
    from micros_tooling.storage.packages import integer
    integer(pin, 0, 255, context)
    capabilities = board_capabilities(board.get('profile', ''), board.get('chip'))
    if kind in ('input', 'output'):
        if capabilities:
            validate_gpio(capabilities, pin, kind, 'none', context)
        return 'none'
    require(capabilities is not None, f'{context}: verified board and MCU metadata required for {kind}')
    validate_gpio(capabilities, pin, 'input', 'none', context)
    if kind == 'analog':
        require(capabilities['runtime'].get('analog_gpio', True),
                f'{context}: analog GPIO is not supported by the current micros runtime for {board["profile"]}')
        adc = capabilities['pins'][pin].get('adc')
        require(adc is not None, f'{context}: GPIO{pin} is not an analog input')
        require(adc['unit'] == 1, f'{context}: current runtime supports ADC1 only')
        return 'none'
    required = {'pullup': 'up', 'pulldown': 'down'}[kind]
    external = capabilities['connections'].get(str(pin), {}).get('external_pull', 'unknown')
    require(external not in ('up', 'down') or external == required,
            f'{context}: GPIO{pin} has an external pull-{external}, but service requires pull-{required}')
    if external == required:
        return 'none'
    validate_gpio(capabilities, pin, 'input', required, context)
    return required


def pin_listing(board):
    capabilities = board_capabilities(board["profile"], board.get("chip"))
    require(capabilities is not None, f"No verified pin catalogue for {board['profile']}")
    selected = {item["pin"]: item for item in board.get("gpio", [])}
    rows = []
    rmt = capabilities["peripherals"].get("rmt")
    for pin, info in sorted(capabilities["pins"].items()):
        connection = capabilities["connections"].get(str(pin), {})
        access = ("available" if capabilities["board"].get("generic") else "exposed") if pin in capabilities["board"]["exposed"] else (
            "onboard" if pin in capabilities["board"]["onboard"] else "unverified")
        reserved = pin in capabilities["runtime"]["reserved"]
        rows.append(dict(pin=pin, **info, access=access, reserved=reserved,
                         rmt_tx=bool(rmt and info[rmt["tx_requires"]]), rmt_rx=bool(rmt and info[rmt["rx_requires"]]),
                         label=connection.get("label", ""), external_pull=connection.get("external_pull", "unknown"),
                         notes=connection.get("notes", ""), assigned=selected.get(pin, {}).get("name"),
                         configured=selected.get(pin)))
    return dict(chip=capabilities["chip"], board=capabilities["board"], runtime=capabilities["runtime"],
                peripherals=capabilities["peripherals"], pins=rows)


def format_pins_table(report):
    pin_label = "PIN " if any("chip_pin" in pin for pin in report["pins"]) else "GPIO"
    lines = [f"{report['board']['profile']} — {report['chip']['id']}", report["board"].get("numbering", "GPIO numbers"),
             f"{pin_label}  IN OUT  INTERNAL PULLS  RMT TX/RX  ADC     ACCESS       ASSIGNED / CONNECTION"]
    for pin in report["pins"]:
        access = "reserved" if pin["reserved"] else pin["access"]
        details = " / ".join(filter(None, (pin["assigned"], pin["label"])))
        if pin["external_pull"] != "unknown": details += f" (board pull-{pin['external_pull']})"
        if pin["notes"]: details += " — " + pin["notes"]
        adc = f"{pin['adc']['unit']}:{pin['adc']['channel']}" if "adc" in pin else "-"
        lines.append(f"{pin['pin']:>4}  {int(pin['input']):>2} {int(pin['output']):>3}  {','.join(pin['pulls']):<14}  "
                     f"{int(pin['rmt_tx'])}/{int(pin['rmt_rx']):<7}  {adc:<6}  {access:<12} {details}")
    if "rmt" in report["peripherals"]:
        lines.append(f"RMT columns describe routing eligibility, not service grants; TX/RX share {report['peripherals']['rmt']['shared_channels']} hardware channels.")
    else:
        lines.append("This chip has no RMT peripheral.")
    if not report["runtime"].get("analog_gpio", True):
        lines.append("ADC columns describe hardware; analog GPIO is not implemented by the current micros runtime.")
    lines += [
              "Internal pulls describe hardware support. Current micros runtime supports pull=none only.",
              "Unknown external pull means unverified board wiring, not absence of a resistor."]
    return "\n".join(lines)


def format_pins(report, *, all_pins=False, pin_number=None):
    if all_pins:
        return format_pins_table(report)
    title = report['board']['profile'].replace('_', ' ').title().replace('Esp32', 'ESP32').replace('Esp8266', 'ESP8266').replace('Mkr', 'MKR').replace('Wifi', 'WiFi')
    pin_label = "Pin" if any("chip_pin" in pin for pin in report["pins"]) else "GPIO"
    lines = [title, report["board"].get("numbering", "GPIO numbers"), ""]
    if pin_number is not None:
        pin = next((p for p in report["pins"] if p["pin"] == pin_number), None)
        require(pin is not None, f"GPIO{pin_number} is not in this chip's pin catalogue")
        mode = "input or output" if pin["output"] else "input only"
        lines += [f"{pin_label}{pin_number}" + (f" — {pin['label']}" if pin['label'] else ""),
                  f"  Chip supports: {mode}",
                  f"  Internal resistors: {', '.join('pull-' + pull for pull in pin['pulls'] if pull != 'none') or 'none'}",
                  "  Board resistor: " + (f"pull-{pin['external_pull']}" if pin['external_pull'] != 'unknown' else "not verified"),
                  f"  Connection: {pin['access']}"]
        if pin['assigned']: lines.append(f"  Configured as: {pin['assigned']}")
        if pin['reserved']: lines.append("  Unavailable: " + report["runtime"]["reserved_reason"])
        if pin['notes']: lines.append(f"  Note: {pin['notes']}")
        lines.append("  RMT hardware: " + ("transmit and receive" if pin['rmt_tx'] else "receive only") if "rmt" in report["peripherals"] else "  RMT hardware: unavailable")
        if 'adc' in pin:
            lines.append(f"  Analog input: ADC{pin['adc']['unit']}, channel {pin['adc']['channel']}")
            if not report["runtime"].get("analog_gpio", True): lines.append("  Analog GPIO is not implemented by the current micros runtime.")
            if report['chip']['id'] == 'esp32' and pin['adc']['unit'] == 2: lines.append("  ADC2 is shared with Wi-Fi; micros currently exposes ADC1 only.")
        lines += ["", 'micros currently accepts pull = "none" only; up/down still need runtime support.',
                  "RMT eligibility does not allocate a peripheral channel." if "rmt" in report["peripherals"] else ""]
        return "\n".join(lines)

    connected = [
        p for p in report['pins'] if (p.get('configured') or {}).get('owner')]
    lines.append("Service connections (from your unit file)")
    if not connected: lines.append("  No service connections listed.")
    for pin in connected:
        configuration = pin['configured']
        details = configuration.get('direction', 'direction unspecified')
        if pin['external_pull'] != 'unknown': details += f"; board has a pull-{pin['external_pull']}"
        elif pin['label']: details += f"; {pin['label']}"
        lines.append(f"  {pin_label}{pin['pin']:<2}  {configuration['owner']:<30} {details}")

    candidates = [p for p in report['pins'] if p['access'] in ('exposed', 'available') and not p['reserved']
                  and not p['assigned'] and p['pin'] not in report['board']['onboard']]
    ordinary = [p for p in candidates if not p['notes']]
    conditional = [p for p in candidates if p['notes']]
    numbers = lambda pins: ', '.join(str(p['pin']) for p in pins) or 'none'
    lines += ["", "Available GPIOs (verify module wiring)" if report["board"].get("generic") else "Unused header pins (check your external wiring)",
              "  Input or output: " + numbers([p for p in ordinary if p['output']]),
              "  Input only:      " + numbers([p for p in ordinary if not p['output']])]
    if conditional:
        lines.append("  Check before using:")
        for pin in conditional:
            lines.append(f"    {pin_label}{pin['pin']}: {pin['notes']}")
    lines += ["", "Other board connections"]
    for pin in report['pins']:
        if pin['pin'] in report['board']['onboard'] and pin not in connected:
            lines.append(f"  {pin_label}{pin['pin']}: {pin['label'] or 'onboard circuit'}")
    lines += ["", 'Pull resistors: micros currently accepts pull = "none" only.',
              '  This leaves external resistors connected; it does not mean the pin is floating.',
              f"Hidden: {sum(p['reserved'] for p in report['pins'])} reserved pins and "
              f"{sum(p['access'] == 'unverified' and not p['reserved'] for p in report['pins'])} pins with unverified board access.",
              "Details: add --pin NUMBER for one pin, --all for the full table, or --json."]
    return "\n".join(lines)


def unit_pin_listing(path):
    """Inspect capabilities even when the unit contains invalid pull settings."""
    unit = read_toml(path)
    from micros_tooling.config.unit_model import contracts
    models = contracts(unit, path)
    board = copy.deepcopy(unit["board"])
    gpio = [dict(resource, name=name) for name, resource in board.get("gpio", {}).items()]
    for alias, service in unit.get("services", {}).items():
        if not service.get('enabled', True): continue
        for role, pin in service.get('pins', {}).items():
            hardware = models.get(alias, (None, {}))[1].get('hardware', {}).get(role, {})
            gpio.append(dict(pin=pin, name=role, owner=f'{alias}.{role}',
                             direction=hardware.get('direction', 'unknown'), type=hardware.get('_type')))
        for role, binding in service.get("gpio_bindings", {}).items():
            if isinstance(binding, dict) and "pin" in binding:
                gpio.append(dict(binding, name=binding.get("name", role), owner=f"{alias}.{role}"))
            elif isinstance(binding, str):
                for resource in gpio:
                    if resource['name'] == binding:
                        resource['owner'] = f"{alias}.{role}"
    board["gpio"] = gpio
    return pin_listing(board)
