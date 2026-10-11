"""Compile a physical setup with typed service ports into existing unit recipes.

This is an offline authoring layer. It adds no transport, runtime ABI, or live
route admission. Paths are relative to their declaring file; nothing deep-merges.
"""

import copy
from pathlib import Path
import re

from micros_tooling.config.composition import finish, reference, service, table
from micros_tooling.config.configuration import read_toml, valid_identifier
from micros_tooling.config.resources import board_definition, validate_bindings
from micros_tooling.communication.relay_config import server_settings
from micros_tooling.storage.packages import (
    MAX_CHANNELS, MAX_CHANNEL_DEPTH, MAX_PAYLOAD, MAX_SERVICES,
    canonical_schema, digest, identifier, integer, require,
)

PROFILES = {"adafruit_feather_esp32_v2": 2, "esp32_d0wd_v3_no_controls": 2,
            "esp8266_4mb": 6, "arduino_mkr_wifi_1010": 5}


def mapping(value, context):
    require(isinstance(value, dict), f"{context}: expected a table")
    return value


def interface(path):
    from micros_tooling.config.declarations import interface as resolve_interface
    spec = resolve_interface(path)
    spec['name'] = read_toml(path)['interface'].get('name', spec['interface'])
    return spec


def port_contract(manifest, spec, context):
    table(spec, {"interface", "kind", "policy", "depth"}, {"interface"}, context)
    contract = interface(reference(manifest, spec["interface"]))
    if contract.pop('_delivery', False):
        for field in ('kind', 'policy'):
            require(field not in spec or spec[field] == contract.get(field),
                    f'{context}: {field} belongs to the shared interface')
    kind = spec.get("kind", contract.get('kind'))
    require(kind in (None, "state", "action", "event"), f"{context}: invalid kind")
    policy = spec.get("policy", contract.get('policy', "latest"))
    require(policy in ("latest", "stream"), f"{context}: invalid policy")
    depth = integer(spec.get("depth", 1), 1, MAX_CHANNEL_DEPTH, f"{context}: depth")
    require(policy != "latest" or depth == 1, f"{context}: latest requires depth 1")
    require(kind is None or (policy == "latest" and depth == 1 and contract["max_payload"] <= 64),
            f"{context}: coordination requires latest, depth 1, payload <=64")
    contract.update(policy=policy, depth=depth)
    # Compare contents rather than the path spelling of two equivalent schemas.
    signature = {k: v for k, v in contract.items() if k != "schema"}
    signature.update(kind=kind, schema=digest(canonical_schema(Path(contract["schema"]).read_bytes())))
    return contract, kind, signature


def bind_hardware(definition, selection, board, owners, context):
    hardware = mapping(definition.pop("hardware", {}), f"{context}: hardware")
    capabilities = definition["capabilities"]
    table(capabilities, {"gpio", "timers"}, {"gpio", "timers"}, f"{context}: capabilities")
    grants = capabilities["gpio"]
    require(isinstance(grants, list) and all(valid_identifier(g) for g in grants)
            and len(set(grants)) == len(grants) and set(hardware) == set(grants),
            f"{context}: declare hardware requirements for every GPIO capability")
    pins = mapping(selection.get("pins", {}), f"{context}: pins")
    require(set(pins) == set(grants), f"{context}: pins must bind exactly {', '.join(grants) or 'no GPIOs'}")
    resources = board.setdefault("gpio", {})
    for name in grants:
        spec = hardware[name]
        table(spec, {"direction", "fixed_pin", "_type"}, {"direction"}, f"{context}.{name}")
        require(spec["direction"] in ("input", "output"), f"{context}.{name}: invalid direction")
        assigned = pins[name]
        if isinstance(assigned, str):
            require(assigned == name and assigned in resources,
                    f"{context}.{name}: named pin must reference board GPIO {name}")
            pin = resources[assigned]["pin"]
        else:
            pin = integer(assigned, 0, 255, f"{context}.{name}: GPIO pin")
        if "fixed_pin" in spec:
            fixed = integer(spec["fixed_pin"], 0, 255, f"{context}.{name}: fixed_pin")
            require(pin == fixed, f"{context}.{name}: driver requires GPIO{fixed}; got GPIO{pin}")
        resource = dict(pin=pin, direction=spec["direction"])
        if spec.get('_type'):
            from micros_tooling.config.chips import resolve_pin_type
            pull = resolve_pin_type(board, pin, spec['_type'], f'{context}.{name}')
            if pull != 'none': resource['pull'] = pull
        require(name not in resources or resources[name] == resource,
                f"{context}.{name}: conflicts with board GPIO {name}")
        require(pin not in owners, f"{context}.{name}: GPIO{pin} already owned by {owners.get(pin)}")
        owners[pin] = f"{context}.{name}"
        resources[name] = resource


def compose_setup(path, doc):
    table(doc, {"setup", "management", "devices", "connections", "captures"},
          {"setup", "devices"}, str(path))
    table(doc["setup"], {"name", "format"}, {"name", "format"}, "setup")
    require(type(doc["setup"]["format"]) is int and doc["setup"]["format"] == 1,
            "setup.format must be 1")
    require(isinstance(doc["setup"]["name"], str) and doc["setup"]["name"], "setup.name must be text")
    server = server_settings(doc)
    declared = mapping(doc["devices"], "devices")
    require(declared, "Setup needs devices")
    units, sources, ports, identities = {}, {}, {}, set()
    for device_alias, device in declared.items():
        require(valid_identifier(device_alias), f"Invalid device alias: {device_alias}")
        context = f"{path}: devices.{device_alias}"
        table(device, {"id", "board", "flash_mb", "recovery_button", "gpio", "build", "services", "channel_keys"},
              {"id", "board", "services"}, context)
        identity = device["id"]
        require(isinstance(identity, str) and re.fullmatch(r"[0-9a-f]{12}", identity),
                f"{context}: invalid hardware ID")
        require(identity not in identities, f"Hardware ID selected twice: {identity}")
        identities.add(identity)
        require(valid_identifier(device["board"]), f"{context}: board must be a profile identifier")
        require(device["board"] in PROFILES, f"{context}: unsupported setup board profile {device['board']}")
        board = dict(profile=device["board"], **{k: copy.deepcopy(device[k])
                     for k in ("flash_mb", "recovery_button", "gpio") if k in device})
        # Validate any board-owned resources before resolving references to them.
        if "gpio" in board:
            board_definition({k: v for k, v in board.items() if k != "recovery_button"})
        build = device.get("build", {"name": doc["setup"]["name"]})
        table(build, {"name", "required_sdkconfig", "disabled_sdkconfig"}, set(), f"{context}: build")
        require(isinstance(build.get("name", ""), str), f"{context}: build.name must be text")
        settings = mapping(build.get("required_sdkconfig", {}), f"{context}: required_sdkconfig")
        require(all(isinstance(v, str) for v in settings.values()), f"{context}: SDK settings must be strings")
        disabled = build.get("disabled_sdkconfig", [])
        require(isinstance(disabled, list) and all(isinstance(v, str) for v in disabled),
                f"{context}: disabled_sdkconfig must be a list of settings")
        require(not set(settings) & set(disabled), f"{context}: SDK setting both required and disabled")
        unit = dict(project=copy.deepcopy(build),
                    unit={"device_id": identity}, board=board, services={}, channels={})
        if "management" in doc:
            unit["management"] = copy.deepcopy(doc["management"])
        selected = mapping(device["services"], f"{context}: services")
        require(selected, f"{context}: select at least one service")
        owners, peripherals, manifests = {}, {}, {}
        for alias, selection in selected.items():
            label = f"{device_alias}.{alias}"
            require(valid_identifier(alias) and alias != "bridge", f"{label}: invalid or reserved service alias")
            table(selection, {"manifest", "pins", "config", "memory"}, {"manifest"}, label)
            manifest = reference(path, selection["manifest"])
            manifests[alias] = str(manifest)
            definition = service(manifest, authored=True)
            requirements = definition.pop("requirements", {})
            table(requirements, {"profiles", "exclusive", "instance"}, set(), f"{manifest}: requirements")
            if "instance" in requirements:
                require(alias == requirements["instance"],
                        f"{label}: current generated service API requires instance name {requirements['instance']}")
            if "profiles" in requirements:
                profiles = requirements["profiles"]
                require(isinstance(profiles, list) and profiles and all(valid_identifier(p) for p in profiles),
                        f"{manifest}: profiles must be a nonempty list of profile identifiers")
                require(board["profile"] in profiles, f"{label}: driver supports only {', '.join(profiles)}")
            exclusive = requirements.get("exclusive", [])
            require(isinstance(exclusive, list) and all(isinstance(p, str) and p for p in exclusive),
                    f"{manifest}: exclusive must be a list of peripheral names")
            for peripheral in exclusive:
                require(peripheral not in peripherals,
                        f"{label}: peripheral {peripheral} already owned by {peripherals.get(peripheral)}")
                peripherals[peripheral] = label
            bind_hardware(definition, selection, board, owners, label)
            default_memory = definition.pop("memory", None)
            definition["memory"] = copy.deepcopy(selection.get("memory", default_memory))
            require(definition["memory"] is not None, f"{label}: service or setup must declare a memory budget")
            if "config" in selection:
                mapping(selection["config"], f"{label}: config")
                definition["config"] = copy.deepcopy(selection["config"])
            for direction in ("subscriptions", "publications"):
                declarations = mapping(definition.pop(direction, {}), f"{manifest}: {direction}")
                bindings = {}
                for port, spec in declarations.items():
                    require(valid_identifier(port), f"{manifest}: invalid port {port}")
                    endpoint = f"{label}.{port}"
                    require(endpoint not in ports, f"{endpoint}: input/output names must be distinct")
                    contract, kind, signature = port_contract(manifest, spec, endpoint)
                    binding = {} if kind is None else {"kind": kind}
                    bindings[port] = binding
                    ports[endpoint] = dict(device=device_alias, direction=direction, contract=contract,
                                           signature=signature, kind=kind, binding=binding)
                if bindings:
                    definition[direction] = bindings
            unit["services"][alias] = definition
        resolved_board = board_definition(board)
        validate_bindings({k: resolved_board[k] for k in ("gpio", "recovery_button")},
                          target=PROFILES[board["profile"]])
        units[device_alias] = unit
        sources[device_alias] = dict(setup=str(path), services=manifests, peripherals=peripherals)

    def endpoint(value, direction):
        require(isinstance(value, str) and value in ports, f"Unknown endpoint: {value}")
        port = ports[value]
        require(port["direction"] == direction, f"{value}: expected a {direction} port")
        return port

    # Every input has one explicit source. Ordinary local fan-out shares the
    # producer's bounded channel. Cross-device fan-out remains forbidden by finish.
    incoming, local, remote, names = {}, [], [], set()
    connections = doc.get("connections", [])
    require(isinstance(connections, list), "connections must be an array of tables")
    for connection in connections:
        table(connection, {"name", "from", "to", "drop_first"}, {"from", "to"}, "connection")
        source, target = connection["from"], connection["to"]
        output, input_port = endpoint(source, "publications"), endpoint(target, "subscriptions")
        require(target not in incoming, f"{target}: input already has a source")
        require(output["signature"] == input_port["signature"], f"{source} -> {target}: endpoint contracts differ")
        name = connection.get("name", f"{source}->{target}")
        require(isinstance(name, str) and name and name not in names, "Connection names must be nonempty and unique")
        names.add(name)
        drop = integer(connection.get("drop_first", 0), 0, 100, f"{name}: drop_first")
        incoming[target] = source
        if output["device"] == input_port["device"]:
            require(output["kind"] is None,
                    f"{name}: local coordination is not supported by setup format 1; use ordinary local ports")
            require(drop == 0, f"{name}: drop_first applies only to network coordination")
            local.append(dict(source=source, target=target))
        else:
            require(output["kind"] is not None,
                    f"{name}: ordinary cross-device streams are unsupported; use a supported adapter or coordination port")
            require(server,
                    f"{name}: network coordination requires management.server.url")
            remote.append(dict(name=name, **{"from": source, "to": target}, drop_first=drop))
    for name, port in ports.items():
        require(port["direction"] != "subscriptions" or name in incoming, f"{name}: required input has no source")

    # Explicit keys preserve existing activations during migration. Otherwise keys
    # are assigned in sorted endpoint order. No hashes or implicit global registry.
    def root(name):
        source = incoming.get(name)
        return source if source and ports[source]["device"] == ports[name]["device"] else name

    for alias, unit in units.items():
        roots = sorted({root(name) for name, port in ports.items() if port["device"] == alias})
        overrides = mapping(declared[alias].get("channel_keys", {}), f"{alias}: channel_keys")
        assigned, used = {}, set()
        for short, key in overrides.items():
            name = f"{alias}.{short}"
            require(name in ports, f"{alias}: unknown channel_keys endpoint {short}")
            key = integer(key, 1, 32, f"{alias}.{short}: channel key")
            owner = root(name)
            require(owner not in assigned, f"{alias}.{short}: channel key is already assigned through another port")
            require(key not in used, f"{alias}: duplicate channel key {key}")
            assigned[owner] = key
            used.add(key)
        require(len(roots) <= MAX_CHANNELS, f"{alias}: at most {MAX_CHANNELS} local channels are supported")
        symbols = {}
        for name in roots:
            if name not in assigned:
                assigned[name] = next(k for k in range(1, 33) if k not in used)
                used.add(assigned[name])
            symbol = name.split(".", 1)[1].replace(".", "_")
            require(symbol not in unit["channels"], f"{alias}: generated channel name collision for {name}")
            symbols[name] = symbol
            unit["channels"][symbol] = dict(ports[name]["contract"], key=assigned[name])
        channel_names = [c["name"] for c in unit["channels"].values()]
        require(len(set(channel_names)) == len(channel_names), f"{alias}: interface channel name used on multiple channels")
        for name, port in ports.items():
            if port["device"] == alias:
                port["binding"]["channel"] = symbols[root(name)]

    captures = mapping(doc.get("captures", {}), "captures")
    lowered = dict(deployment={"name": doc["setup"]["name"]}, connections=remote, streams=captures)
    result = finish(lowered, units, sources)
    for alias, unit in units.items():
        require(len(unit["services"]) <= MAX_SERVICES,
                f"{alias}: at most {MAX_SERVICES} services including the generated capture bridge")
        names = [s["name"] for s in unit["services"].values()]
        require(len(names) == len(set(names)), f"{alias}: duplicate service name; multiple instances of one service are unsupported")
        for service_alias, selected in unit["services"].items():
            for direction in ("subscriptions", "publications"):
                bindings = [b["channel"] for b in selected.get(direction, {}).values()]
                require(len(bindings) == len(set(bindings)),
                        f"{alias}.{service_alias}: duplicate channel endpoint in {direction}")
    result.update(setup=str(path), local_connections=local)
    return result


def describe_setup(result):
    lines = [result["name"], f"  setup: {result['setup']}"]
    for alias, unit in result["units"].items():
        lines.append(f"\n  {alias} ({unit['unit']['device_id']}) — {unit['board']['profile']}")
        resources = unit["board"].get("gpio", {})
        for name, selected in unit["services"].items():
            memory = selected["memory"]
            generated = " [generated for capture]" if name == "bridge" else ""
            lines.append(f"    {name}: {selected['name']}{generated}; {memory['arena']}, stack {memory.get('stack_bytes', 4096)} B")
            manifest = result["sources"][alias]["services"].get(name)
            if manifest:
                lines.append(f"      manifest: {manifest}")
            for grant in selected["capabilities"]["gpio"]:
                resource = resources[grant]
                lines.append(f"      {grant} = GPIO{resource['pin']} ({resource['direction']})")
            for key, value in selected.get("config", {}).items():
                lines.append(f"      {key} = {value}")
        for peripheral, owner in result["sources"][alias]["peripherals"].items():
            lines.append(f"    exclusive peripheral: {peripheral} → {owner}")
        for name, resource in resources.items():
            if not any(name in s["capabilities"]["gpio"] for s in unit["services"].values()):
                lines.append(f"    board GPIO: {name} = GPIO{resource['pin']} ({resource['direction']})")
        recovery = unit["board"].get("recovery_button")
        if recovery:
            lines.append(f"    recovery button: {recovery} (GPIO{resources[recovery]['pin']})")
        for key, value in unit.get("project", {}).get("required_sdkconfig", {}).items():
            lines.append(f"    build: {key}={value}")
        for key in unit.get("project", {}).get("disabled_sdkconfig", []):
            lines.append(f"    build: {key}=disabled")
        bytes_ = sum(c["depth"] * c["max_payload"] for c in unit["channels"].values())
        lines.append(f"    channel payload storage: {bytes_} B ({len(unit['channels'])} channels; excludes overhead)")
    for connection in result["local_connections"]:
        lines.append(f"\n  local: {connection['source']} → {connection['target']}")
    for route in result["coordination"]["routes"]:
        device, service_alias, port = route["source"].split(".")
        kind = result["units"][device]["services"][service_alias]["publications"][port]["kind"]
        suffix = f"; drop first {route['drop_first']}" if route["drop_first"] else ""
        lines.append(f"  network {kind}: {route['source']} → {route['target']}{suffix}")
    for name, capture in result["streams"].items():
        lines.append(f"  capture: {capture['from']} → viewer port {name}")
    if result["coordination"]["routes"]:
        lines.append("\n  Network routes must be admitted after the participating units are deployed.")
    lines.append("  Offline configuration checks only; compiled sizes and live delivery are checked later.")
    return "\n".join(lines)
