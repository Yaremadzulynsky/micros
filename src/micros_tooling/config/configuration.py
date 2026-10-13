"""Typed deployment configuration and the human-facing TOML application recipe."""

import hashlib
import json
import re
import struct
from pathlib import Path

import tomli
from micros_tooling.storage.packages import MAX_HANDLES, integer, require
from micros_tooling.config.resources import load_board, select_board, resource_header

IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*\Z")
MAX_CONFIG_BYTES = 256
C_KEYWORDS = set(
    "auto break case char const continue default do double else enum extern float for "
    "goto if inline int long register restrict return short signed sizeof static struct "
    "switch typedef union unsigned void volatile while class new delete this template typename "
    "operator true false nullptr namespace using public private protected virtual constexpr "
    "decltype friend try catch throw noexcept alignas alignof static_assert thread_local".split()
)


def valid_identifier(value):
    return (
        isinstance(value, str)
        and bool(IDENTIFIER.fullmatch(value))
        and value not in C_KEYWORDS
    )


def read_toml(path):
    try:
        return tomli.loads(Path(path).read_text())
    except (OSError, tomli.TOMLDecodeError) as error:
        raise ValueError(f"{path}: {error}") from error


def unit_identity(path, root=None):
    """A unit recipe is bound to a canonical hardware identity, never a hostname."""
    root = read_toml(path) if root is None else root
    if "unit" not in root:
        return None
    unit = root["unit"]
    require(isinstance(unit, dict) and unit.keys() == {"device_id"},
            "[unit] requires device_id only")
    identity = unit["device_id"]
    require(isinstance(identity, str) and re.fullmatch(r"[0-9a-f]{12}", identity),
            "unit.device_id must be 12 lowercase hexadecimal MAC digits")
    require(Path(path).stem == identity, "Unit filename must match unit.device_id")
    require("board" in root, "Unit files must contain their own [board] definition")
    return identity


def select_unit(directory, identity, project=None):
    """Resolve a complete unit recipe and reject cross-unit overrides."""
    require(isinstance(identity, str), "Selected device has no hardware identity")
    identity = identity.lower().replace(":", "")
    require(re.fullmatch(r"[0-9a-f]{12}", identity), "Invalid selected device identity")
    path = Path(project) if project is not None else Path(directory) / (identity + ".toml")
    require(path.is_file(), f"Unit configuration missing: {path}")
    require(unit_identity(path) == identity,
            f"Unit configuration does not match selected hardware {identity}: {path}")
    return path.resolve()


def fields_for(name, definition):
    require(valid_identifier(name), "configuration name must be a C identifier")
    require(
        isinstance(definition, dict) and definition.keys() <= {"name", "fields"},
        f"{name}: expected configuration name and fields",
    )
    fields = definition.get("fields", {})
    require(
        isinstance(fields, dict) and 1 <= len(fields) <= 62,
        f"{name}: expected 1..62 configuration fields",
    )
    for field, spec in fields.items():
        require(valid_identifier(field), f"{name}: invalid field name {field}")
        require(isinstance(spec, dict), f'{name}.{field}: expected a type definition')
        from micros_tooling.config.declarations import field as resolve_field
        resolved = resolve_field({k:v for k,v in spec.items() if k != 'default'}, context=f'{name}.{field}')
        require(resolved['type'] in ('uint32', 'enum'), f'{name}.{field}: unsupported startup type {resolved["type"]}')
        require("default" in spec, f"{name}.{field}: missing default")
        numeric_value(name, field, spec, spec["default"])
    return fields


def numeric_value(name, field, spec, value):
    if spec["type"] == "enum":
        require(
            value in spec["choices"],
            f'{name}.{field}: expected one of {spec["choices"]}',
        )
        return spec["choices"].index(value)
    require(
        type(value) is int
        and spec.get("min", 0) <= value <= spec.get("max", 0xFFFFFFFF),
        f'{name}.{field}: expected integer {spec.get("min", 0)}..{spec.get("max", 0xffffffff)}',
    )
    return value


def config_artifacts(name, definition, overrides):
    fields = fields_for(name, definition)
    require(
        isinstance(overrides, dict) and overrides.keys() <= fields.keys(),
        f"{name}: unknown configuration setting",
    )
    # Order is part of the encoding. Hash the normalized schema including defaults and bounds.
    canonical = json.dumps(
        list(fields.items()), sort_keys=True, separators=(",", ":")
    ).encode()
    identity = hashlib.sha256(name.encode() + b"\0" + canonical).digest()[:8]
    values = [
        numeric_value(name, field, spec, overrides.get(field, spec["default"]))
        for field, spec in fields.items()
    ]
    payload = identity + struct.pack("<" + "I" * len(values), *values)
    require(len(payload) <= MAX_CONFIG_BYTES, "configuration exceeds 256-byte budget")
    lines = [
        f"/* Generated from {name} configuration; edit the configuration declaration, not this file. */",
        f"#ifndef MICROS_GENERATED_{name.upper()}_CONFIG_H",
        f"#define MICROS_GENERATED_{name.upper()}_CONFIG_H",
        "#include <micros/service.h>",
    ]
    for field, spec in fields.items():
        if spec["type"] == "enum":
            lines.append(
                f'#define {name.upper()}_{field.upper()}_COUNT UINT32_C({len(spec["choices"])})'
            )
            for index, choice in enumerate(spec["choices"]):
                lines.append(
                    f"#define {name.upper()}_{field.upper()}_{choice.upper()} UINT32_C({index})"
                )
    lines += [
        f"/** @brief Validated startup configuration for {name}. */",
        "typedef struct {",
    ]
    lines += [f"    uint32_t {field};" for field in fields]
    lines += [
        f"}} {name}_config_t;",
        "/** @brief Decode explicit little-endian values; empty payload selects defaults.",
        " * Reject unknown schemas, lengths or values without modifying output. */",
        f"static inline micros_result_t {name}_config_decode(const uint8_t *data, uint32_t bytes,",
        f"                                                    {name}_config_t *output)",
        "{",
        "    if (!output || (bytes && !data)) return MICROS_ERROR_INVALID_ARGUMENT;",
        f"    {name}_config_t value = {{",
    ]
    lines += [
        f'        UINT32_C({numeric_value(name, field, spec, spec["default"])}), /* {field} */'
        for field, spec in fields.items()
    ]
    lines += [
        "    };",
        "    if (bytes) {",
        f"        if (bytes != {len(payload)}u) return MICROS_ERROR_INVALID_ARGUMENT;",
    ]
    lines += [
        f"        if (data[{i}] != {byte}u) return MICROS_ERROR_INVALID_ARGUMENT;"
        for i, byte in enumerate(identity)
    ]
    for index, (field, spec) in enumerate(fields.items()):
        offset = 8 + 4 * index
        lines += [
            f"        value.{field} = (uint32_t)data[{offset}] | (uint32_t)data[{offset+1}] << 8 |",
            f"                         (uint32_t)data[{offset+2}] << 16 | (uint32_t)data[{offset+3}] << 24;",
        ]
        low = spec.get("min", 0) if spec["type"] == "uint32" else 0
        high = (
            spec.get("max", 0xFFFFFFFF)
            if spec["type"] == "uint32"
            else len(spec["choices"]) - 1
        )
        checks = ([f"value.{field} < UINT32_C({low})"] if low else []) + (
            [f"value.{field} > UINT32_C({high})"] if high < 0xFFFFFFFF else []
        )
        if checks:
            lines.append(
                "        if ("
                + " || ".join(checks)
                + ") return MICROS_ERROR_INVALID_ARGUMENT;"
            )
    lines += [
        "    }",
        "    *output = value;",
        "    return MICROS_OK;",
        "}",
        "#endif",
        "",
    ]
    return "\n".join(lines), payload


def _load_project(path, overlay=None, board=None):
    path = Path(path).resolve()
    require(path.suffix != ".json",
            "Application declarations must be TOML; resolved JSON recipes are output only.")
    root = read_toml(path)
    require(
        root.keys() <= {"project", "services", "channels", "management", "board", "unit"}, "Unknown project setting"
    )
    unit_identity(path, root)
    require(isinstance(root.get("services"), dict), "Expected [services.NAME] tables")
    from micros_tooling.communication.relay_config import server_settings
    server_settings(root)
    if overlay:
        overrides = read_toml(overlay)
        require(
            overrides.keys() == {"services"},
            "Overlay may contain only service configuration",
        )
        for alias, settings in overrides["services"].items():
            require(
                alias in root["services"] and settings.keys() == {"config"},
                f"{alias}: overlay may only override configuration of a selected service",
            )
            root["services"][alias].setdefault("config", {}).update(settings["config"])
    project = root.get("project", {})
    require(
        project.keys() <= {"name", "required_sdkconfig", "disabled_sdkconfig"},
        "Unknown project field",
    )
    recipe = dict(
        format=1,
        name=project.get("name", path.stem),
        services=[],
        required_sdkconfig=dict(project.get("required_sdkconfig", {})),
    )
    recipe["required_sdkconfig"].update(
        {key: None for key in project.get("disabled_sdkconfig", [])}
    )
    from micros_tooling.config.unit_model import contracts, gpio_directions, channels as resolve_channels
    models = contracts(root, path)
    gpio_directions(root, models)
    resolve_channels(root, path, models)
    channel_definitions = root.get("channels", {})
    board_path = select_board(path, board)
    board = load_board(board_path, document=root if board_path == path else None)
    recipe["board"] = board
    board_gpio = {resource["name"]: resource for resource in board["gpio"]} if board else {}
    for alias, selection in root["services"].items():
        require(
            isinstance(selection, dict)
            and selection.keys()
            <= {
                "source", "enabled", "name", "version", "build",
                "capabilities", "subscriptions", "publications",
                "config", "config_schema", "memory", "contract", "gpio_bindings", "pins", "expose_commands",
            },
            f"{alias}: unknown service setting",
        )
        require(
            type(selection.get("enabled", True)) is bool,
            f"{alias}: enabled must be boolean",
        )
        if not selection.get("enabled", True):
            continue
        require('pins' not in selection, f'{alias}: pins require a service contract')
        memory = selection.get("memory", {})
        require(isinstance(memory, dict) and {"arena"} <= set(memory) <= {"arena", "stack_bytes"}
                and memory["arena"] in ("RAM", "PSRAM"),
                f'{alias}: memory.arena must explicitly be "RAM" or "PSRAM"')
        stack_bytes = integer(memory.get("stack_bytes", 4096), 1, 16384,
                              f"{alias}: memory.stack_bytes")
        from micros_tooling.config.resources import board_psram_bytes
        require(memory["arena"] != "PSRAM" or board_psram_bytes(board),
                f'{alias}: PSRAM arena requested but selected board has no PSRAM')
        directory = (path.parent / selection["source"]).resolve()
        if "contract" in selection:
            from micros_tooling.config.service_contract import resolve_service_contract
            selection, contract_path, contract = resolve_service_contract(alias, selection, directory, models[alias][1])
        build = selection.get("build", {})
        require(
            isinstance(build, dict)
            and build.keys() <= {"sources", "defines", "descriptor", "api", "lifecycle"},
            f"{alias}: unknown build setting",
        )
        service = dict(build, name=selection["name"], version=selection["version"], arena=memory["arena"], stack_bytes=stack_bytes)
        lifecycle = service.pop("lifecycle", "manual")
        require(lifecycle in ("manual", "hooks"), f"{alias}: invalid build.lifecycle")
        require(lifecycle != "hooks" or "contract" in selection, "Hook lifecycle requires a service contract")
        api_name = service.pop("api", alias)
        require(valid_identifier(api_name), f"{alias}: build.api must be a C identifier")
        service["slot"] = len(recipe["services"])
        service["sources"] = [str(directory / source) for source in service["sources"]]
        capabilities = selection["capabilities"]
        require(isinstance(capabilities, dict), f"{alias}: capabilities must be a table")
        require("handles" not in capabilities,
                f"{alias}: remove capabilities.handles; micros derives it from timers, GPIO, publications and subscriptions")
        require(capabilities.keys() == {"timers", "gpio"},
                f"{alias}: capabilities must declare timers and gpio")
        integer(capabilities["timers"], 0, MAX_HANDLES, f"{alias}: timers")
        gpio = capabilities["gpio"]
        require(isinstance(gpio, list), f"{alias}: gpio must be a list")
        require(all(valid_identifier(name) for name in gpio),
                f"{alias}: gpio must name a resource declared under [board.gpio.NAME]; numeric pins are not accepted")
        bindings = selection.get("gpio_bindings", {name: name for name in gpio if isinstance(name, str)})
        require(isinstance(bindings, dict) and set(bindings) == set(gpio),
                f"{alias}: gpio_bindings must bind every logical GPIO exactly once")
        resolved_gpio = []
        for resource in gpio:
            require(valid_identifier(resource),
                    f"{alias}: gpio must name a resource declared under [board.gpio.NAME]; numeric pins are not accepted")
            target = bindings[resource]
            if isinstance(target, dict):
                require("board" in root, f"{alias}: inline GPIO bindings require an embedded [board]")
                target = target.get("name", resource)
            require(isinstance(target, str) and target in board_gpio,
                    f"{alias}: board '{board['profile'] if board else 'unspecified'}' has no GPIO resource '{target}'. "
                    f"Definition: {board_path}. Available resources: {', '.join(board_gpio) or 'none'}. "
                    "Select a compatible application or declare the resource in the selected board file.")
            resolved_gpio.append(dict(board_gpio[target], name=resource))
        require(len(set(gpio)) == len(gpio), f"{alias}: duplicate gpio line")
        require(len({r['line'] for r in resolved_gpio}) == len(resolved_gpio), f"{alias}: duplicate gpio line binding")
        generated_directory = directory
        if "contract" in selection:
            require(valid_identifier(alias), f"{alias}: service alias must be a C identifier")
            from micros_tooling.config.service_contract import validate_service_contract
            validate_service_contract(path, alias, selection, contract_path, contract, resolved_gpio, channel_definitions, board)
            # Isolate bindings for multiple instances and units sharing source code.
            from micros_tooling.config.layout import host_directory
            project_directory = path.parent.parent if "unit" in root else host_directory(path)
            generated_directory = project_directory / "build" / "units" / path.stem / "services" / alias
        service["capabilities"] = dict(capabilities)
        service["capabilities"]["gpio"] = [resource["line"] for resource in resolved_gpio]
        service["channels"], service["schemas"] = [], {}
        service["_interface"] = dict(name=api_name, directory=str(generated_directory), source_directory=str(directory), ports=[],
                                    gpio=resolved_gpio)
        if "contract" in selection:
            from micros_tooling.config.artifacts import service_directory
            service["_contract"] = dict(path=str(contract_path), directory=str(service_directory(project_directory, contract_path)), definition=contract)
            service["sources"].append(str(Path(generated_directory) / "generated" / (api_name + "_bindings.c")))
            if lifecycle == "hooks":
                service["sources"].append(str(Path(service["_contract"]["directory"]) / "generated" / (api_name + "_lifecycle.c")))
            from micros_tooling.commands.configuration import prepare
            prepare(service, selection, contract, channel_definitions, service["_contract"]["directory"])
        else:
            require(not selection.get("expose_commands"), "Command exposure requires a service contract")
        for table, access in [
            ("subscriptions", "subscribe"),
            ("publications", "publish"),
        ]:
            for port, binding in selection.get(table, {}).items():
                require(
                    binding.keys() <= {"channel", "kind"} and "channel" in binding, f"{alias}.{port}: expected channel and optional kind"
                )
                require(
                    binding["channel"] in channel_definitions,
                    f"{alias}.{port}: unknown channel",
                )
                channel = dict(channel_definitions[binding["channel"]])
                if "contract" in selection and port in contract.get(table, {}):
                    expected = contract[table][port]
                    channel['accepts_minor'] = expected['accepts_minor']
                kind = binding.get("kind")
                require(kind in (None, "state", "action", "event"), f"{alias}.{port}: unknown coordination kind")
                require(kind is None or (channel["policy"] == "latest" and channel["depth"] == 1 and channel["max_payload"] <= 64),
                        f"{alias}.{port}: coordination requires latest, depth 1, payload <=64")
                service["_interface"]["ports"].append(
                    dict(name=port, access=access, key=channel["key"],
                         schema=str((path.parent / channel["schema"]).resolve()),
                         max_payload=channel["max_payload"], kind=kind)
                )
                if kind is not None: channel["coordination"] = kind
                schema = channel.pop("schema")
                channel.update(access=access, schema=port)
                service["schemas"][port] = str(path.parent / schema)
                service["channels"].append(channel)
        # Each timer, GPIO connection and IPC endpoint owns one runtime handle.
        # Keep this bookkeeping in the resolved manifest, not authored TOML.
        handles = capabilities["timers"] + len(gpio) + len(service["channels"])
        require(handles <= MAX_HANDLES,
                f"{alias}: declared resources need {handles} handles; per-service limit is {MAX_HANDLES}")
        service["capabilities"]["handles"] = handles
        config_schema = selection.get("config_schema", {})
        require(isinstance(config_schema, dict), f"{alias}: config_schema must be a table")
        if config_schema:
            service["_configuration"] = dict(
                name=api_name,
                directory=service.get("_contract", {}).get("directory", str(generated_directory)),
                definition={"name": api_name, "fields": config_schema},
                values=selection.get("config", {}),
            )
            config_artifacts(api_name, service["_configuration"]["definition"], selection.get("config", {}))
        else:
            require(
                not selection.get("config"),
                f"{alias}: this service declares no settings",
            )
        recipe["services"].append(service)
    from micros_tooling.commands.configuration import bridge
    bridge(recipe)
    return recipe


def load_project(path, overlay=None, board=None):
    from micros_tooling.config.diagnostics import located
    try:
        return _load_project(path, overlay, board)
    except ValueError as error:
        raise located(overlay or path, error) from error


def generate_service_headers(project, board=None, recipe=None):
    """Validate and plan every artifact before publishing any generated output."""
    from micros_tooling.config.artifacts import publish
    from micros_tooling.config.interfaces import ipc_artifacts
    from micros_tooling.config.protobuf import compile_schema, compile_text
    from micros_tooling.config.service_generation import artifacts as service_artifacts, bindings
    recipe = recipe if recipe is not None else load_project(project, board=board)
    schemas = {name: text for service in recipe['services'] for name, text in service.get('_generated_schemas', {}).items()}
    protocols, plans = {}, []
    for service in recipe['services']:
        if '_contract' in service:
            contract = service['_contract']
            common = Path(contract['directory']) / 'generated'
            files = service_artifacts(contract['path'], common, model=contract['definition'])
            plans.append((common, contract['path'], files))
            owner = Path(service['_interface']['directory']) / 'generated'
            plans.append((owner, str(Path(project).resolve()) + ':' + service['_interface']['name'],
                          {service['_interface']['name'] + '_bindings.c': bindings(service)}))
            continue
        spec = service.get('_interface')
        if not spec: continue
        owner = Path(spec['directory']) / 'generated'
        files = {spec['name'] + '_resources.h': resource_header(spec['name'], spec.get('gpio', []))}
        if '_configuration' in service:
            config = service['_configuration']
            files[config['name'] + '_config.h'] = config_artifacts(config['name'], config['definition'], {})[0]
        for port in spec['ports']:
            schema = port['schema']
            if schema not in protocols:
                protocols[schema] = compile_text(Path(schema).name, schemas[schema]) if schema in schemas else compile_schema(schema)
            for name, text in protocols[schema]['files'].items():
                require(name not in files or files[name] == text, 'Conflicting generated schema: ' + name)
                files[name] = text
        header, code = ipc_artifacts(spec, protocols)
        files[spec['name'] + '_ipc.h'], files[spec['name'] + '_ipc.c'] = header, code
        plans.append((owner, str(Path(spec['source_directory']).resolve()), files))
    publish(plans)
    return sorted(Path(directory) / name for directory, _, files in plans for name in files if name.endswith('.h'))


if __name__ == "__main__":
    import sys
    generate_service_headers(sys.argv[1], board=sys.argv[2] if len(sys.argv) > 2 else None)
