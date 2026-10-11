"""Resolve service definitions and validate a unit's resource bindings.

Contracts own implementation requirements; units select settings and bindings.
Port requirements use the same fields as SDK channel declarations, without a
board channel key or name. Paths belong to the file that declares them.
"""

import copy

from micros_tooling.config.configuration import read_toml, valid_identifier
from micros_tooling.storage.packages import canonical_schema, identifier, integer, require, MAX_PAYLOAD, MAX_CHANNEL_DEPTH


from micros_tooling.config.declarations import table


def resolve_service_contract(alias, selection, directory, model=None):
    reference = selection["contract"]
    require(isinstance(reference, str) and reference, f"{alias}: contract must be a file path relative to source")
    path = (directory / reference).resolve()
    context = f"{alias}: contract {path}"
    from micros_tooling.config.declarations import contract as load_contract
    contract = model if model is not None else load_contract(path)
    intrinsic = {"version", "build", "capabilities", "config_schema"}
    for field in sorted(intrinsic):
        require(field not in selection,
                f"{context}: {field} belongs to the service contract; remove it from the unit")
    resolved = copy.deepcopy(selection)
    for field in intrinsic:
        resolved[field] = copy.deepcopy(contract[field])
    resolved.setdefault("name", contract["name"])
    identifier(resolved["name"], f"{alias}: name")
    return resolved, path, contract


def validate_service_contract(unit, alias, selection, path, contract, gpio, channels, board=None):
    context = f"{alias}: contract {path}"
    hardware = contract.get("hardware", {})
    table(hardware, {r["name"] for r in gpio}, {r["name"] for r in gpio}, f"{context}: hardware")
    for resource in gpio:
        spec = hardware[resource["name"]]
        label = f"{context}: hardware.{resource['name']}"
        table(spec, {"direction", "fixed_pin", "_type"}, {"direction"}, label)
        require(spec["direction"] in ("input", "output"), f"{label}: invalid direction")
        require(resource["direction"] == spec["direction"], f"{label}: GPIO direction mismatch")
        if spec.get('_type'):
            from micros_tooling.config.chips import resolve_pin_type
            resolve_pin_type(board or {}, resource['pin'], spec['_type'], label)
        if "fixed_pin" in spec:
            integer(spec["fixed_pin"], 0, 39, f"{label}: fixed_pin")
            require(resource["pin"] == spec["fixed_pin"], f"{label}: requires pin {spec['fixed_pin']}")
    seen = set()
    for direction in ("subscriptions", "publications"):
        ports = contract.get(direction, {})
        require(isinstance(ports, dict), f"{context}: {direction} must be a table")
        bindings = selection.get(direction, {})
        table(bindings, set(ports), set(ports), f"{context}: {direction} must bind exactly the declared ports")
        for port, expected in ports.items():
            label = f"{context}: {direction}.{port}"
            require(valid_identifier(port) and port not in seen, f"{label}: invalid or duplicate port")
            seen.add(port)
            fields = {"interface", "major", "minor", "accepts_minor", "schema", "policy", "depth", "max_payload"}
            table(expected, fields | {"kind", "_reference", "min_depth"}, fields, label)
            for field in ("major", "minor"):
                integer(expected[field], 0, 65535, f"{label}: {field}")
            integer(expected["depth"], 1, MAX_CHANNEL_DEPTH, f"{label}: depth")
            integer(expected["max_payload"], 1, MAX_PAYLOAD, f"{label}: max_payload")
            require(isinstance(expected["interface"], str) and expected["interface"], f"{label}: invalid interface")
            accepted = expected["accepts_minor"]
            require(isinstance(accepted, list) and len(accepted) == 2
                    and all(type(v) is int and 0 <= v <= 65535 for v in accepted)
                    and accepted[0] <= expected["minor"] <= accepted[1], f"{label}: invalid accepts_minor")
            require(expected["policy"] in ("latest", "stream")
                    and (expected["policy"] != "latest" or expected["depth"] == 1), f"{label}: invalid policy/depth")
            table(bindings[port], {"channel", "kind"}, {"channel"}, label)
            channel_name = bindings[port]["channel"]
            require(isinstance(channel_name, str) and channel_name in channels, f"{label}: unknown channel")
            channel = channels[channel_name]
            require(isinstance(channel, dict), f"{label}: channel must be a table")
            compared = fields - {"schema"}
            if "_reference" in expected:
                compared -= {"depth", "max_payload", "accepts_minor"}
                require(channel["depth"] >= expected["depth"],
                        f"{unit}: channels.{channel_name}.depth={channel['depth']}; {label} requires at least {expected['depth']}")
                require(channel["max_payload"] >= expected["max_payload"],
                        f"{unit}: channels.{channel_name}.max_payload={channel['max_payload']}; {label} needs {expected['max_payload']} bytes")
            for field in sorted(compared):
                require(channel.get(field) == expected[field],
                        f"{label}: channel {field} mismatch; expected {expected[field]!r}, got {channel.get(field)!r} at {unit}: channels.{channel_name}.{field}")
            require(bindings[port].get("kind") == expected.get("kind"), f"{label}: coordination kind mismatch")
            require(isinstance(expected["schema"], str) and isinstance(channel.get("schema"), str),
                    f"{label}: schema must be a file path")
            expected_schema = path.parent / expected["schema"]
            actual_schema = unit.parent / channel["schema"]
            require(canonical_schema(expected_schema.read_bytes()) == canonical_schema(actual_schema.read_bytes()),
                    f"{label}: channel schema mismatch")
