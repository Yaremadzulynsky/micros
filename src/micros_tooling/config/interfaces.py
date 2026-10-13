"""Generate typed service IPC operations from TOML grants and compiled protobuf schemas."""

import os
from pathlib import Path

from micros_tooling.storage.packages import MAX_PAYLOAD, require, canonical_schema, digest

ROOT = Path(__file__).resolve().parents[3]


def ipc_artifacts(specification, protocols):
    """Emit only granted operations; protobuf encoding stays inside the generated SDK."""
    from micros_tooling.config.configuration import valid_identifier

    name = specification["name"]
    require(valid_identifier(name), "service alias must be a C identifier")
    guard = f"MICROS_GENERATED_{name.upper()}_IPC_H"
    owner = "service contract" if specification.get("independent") else "application declaration"
    header = [
        f"/* Generated from {name} IPC declarations; edit the {owner}, not this file. */",
        f"#ifndef {guard}", f"#define {guard}", "#include <micros/service.h>",
    ]
    implementation = [
        f"/* Generated from {name} IPC declarations; edit the {owner}, not this file. */",
        f'#include "{name}_ipc.h"',
    ]
    ports = specification["ports"]
    independent = specification.get("independent", False)
    if independent:
        implementation.append(f'#include "{name}_bindings.h"')
    if ports:
        private_header = os.path.relpath(ROOT / "src/sdk/abi/internal/micros/ipc.h", Path(specification["directory"]) / "generated")
        implementation.append('#include <micros/ipc.h>' if independent else f'#include "{private_header}"')
    seen = set()
    declarations = []
    for port in ports:
        port_name, access, key = port["name"], port["access"], port["key"]
        require(valid_identifier(port_name), f"{name}: port name must be a C identifier")
        require(port_name not in seen, f"{name}.{port_name}: port names must be unique across publications and subscriptions")
        seen.add(port_name)
        require(type(key) is int and 1 <= key <= 32, f"{name}.{port_name}: channel key must be 1..32")
        require(access in ("publish", "subscribe"), f"{name}.{port_name}: invalid access")
        protocol = protocols[port["schema"]]
        capacity = port["max_payload"]
        require(type(capacity) is int and 1 <= capacity <= MAX_PAYLOAD,
                f"{name}.{port_name}: max_payload must be 1..{MAX_PAYLOAD}")
        require(protocol["maximum"] <= capacity,
                f'{name}.{port_name}: protobuf needs up to {protocol["maximum"]} bytes, exceeds max_payload={capacity}')
        prefix = f"{name}_{port_name}"
        message_type = protocol["type"]
        schema_hash = protocol["sha256"]
        header += [f'#define {prefix.upper()}_SCHEMA_SHA256 "{schema_hash}"']
        header += [f'#include "{protocol["codec"]}"',
                   f"/** @brief Protobuf message carried by the {port_name} port. */",
                   f"typedef {message_type} {prefix}_message_t;"]
        args = "const micros_service_args_t *args"
        bound_key = f"{prefix}_binding()" if independent else f"UINT32_C({key})"
        functions = [
            ("open", args + ", micros_handle_t *handle", "ipc_open",
             [f"return args->api->_ipc->ipc_open(args->context, {bound_key}, MICROS_IPC_{access.upper()}, handle);"],
             "Open this declared port; consumes one instance-owned handle."),
            ("close", args + ", micros_handle_t handle", "ipc_close",
             ["return args->api->_ipc->ipc_close(args->context, handle);"],
             "Release an owned port handle, including during partial-startup cleanup."),
        ]
        if access == "subscribe":
            functions.append(("read", args + f", micros_handle_t handle, {prefix}_message_t *message", "ipc_read", [
                "if (!message) return MICROS_ERROR_INVALID_ARGUMENT;",
                f"uint8_t buffer[{capacity}]; /* TOML channel max_payload bounds this stack buffer. */",
                "uint32_t message_bytes = 0;",
                "micros_message_info_t info;",
                "micros_result_t result = args->api->_ipc->ipc_read(args->context, handle, buffer, sizeof(buffer), &message_bytes, &info);",
                "if (result) return result;",
                "if (message_bytes > sizeof(buffer)) return MICROS_ERROR_CAPACITY;",
                f"return {message_type}_decode(buffer, message_bytes, message);",
            ], "Read and decode without blocking. EMPTY, loss or malformed data leave the message unchanged."))
        else:
            # Replay instruments validate captured wire messages through the same
            # generated codec, without access to the private IPC dispatcher.
            declarations += [
                f"/** Decode a bounded wire message for this declared publication; does not publish. */",
                f"micros_result_t {prefix}_decode(const uint8_t *buffer, uint32_t bytes, {prefix}_message_t *message);",
            ]
            implementation += [
                f"micros_result_t {prefix}_decode(const uint8_t *buffer, uint32_t bytes, {prefix}_message_t *message)",
                "{", f"    if (bytes > {capacity}u) return MICROS_ERROR_CAPACITY;",
                f"    return {message_type}_decode(buffer, bytes, message);", "}",
            ]
            functions.append(("publish", args + f", micros_handle_t handle, const {prefix}_message_t *message", "ipc_publish", [
                f"uint8_t buffer[{capacity}]; /* TOML channel max_payload bounds this stack buffer. */",
                "uint32_t message_bytes = 0;",
                f"micros_result_t result = {message_type}_encode(message, buffer, sizeof(buffer), &message_bytes);",
                "if (result) return result;",
                "return args->api->_ipc->ipc_publish(args->context, handle, buffer, message_bytes);",
            ], "Encode protobuf and synchronously copy it into the channel; no message pointer is retained."))
        kind = port.get("kind")
        if kind:
            header.append('#include <micros/coordination.h>')
            kind_id = {"state": 1, "action": 2, "event": 3}[kind]
            functions[0] = ("open", args + ", micros_handle_t *handle", "coord_open",
                [f"return args->api->_ipc->coord_open(args->context, {bound_key}, MICROS_IPC_{access.upper()}, {kind_id}, handle);"],
                "Open a typed coordination port; runtime owns retention and identity.")
            functions = functions[:2]
            operations = {("state", "publish"): [("set", 1, True)],
                          ("state", "subscribe"): [("read", 2, False)],
                          ("action", "publish"): [("request", 3, True), ("result", 6, False)],
                          ("action", "subscribe"): [("next", 4, False), ("complete", 5, True)],
                          ("event", "publish"): [("emit", 7, True)],
                          ("event", "subscribe"): [("read", 8, False)]}[(kind, access)]
            for operation, opcode, write in operations:
                parameters = args + f", micros_handle_t handle, " + ("const " if write else "") + f"{prefix}_message_t *message, micros_coord_info_t *info"
                body = ["if (!message || !info) return MICROS_ERROR_INVALID_ARGUMENT;",
                        f"uint8_t buffer[{capacity}];", "uint32_t bytes = 0;"]
                if write:
                    body += [f"micros_result_t result = {message_type}_encode(message, buffer, sizeof(buffer), &bytes);",
                             "if (result) return result;",
                             f"return args->api->_ipc->coord(args->context, handle, {opcode}, buffer, sizeof(buffer), &bytes, info);"]
                else:
                    body += [f"micros_result_t result = args->api->_ipc->coord(args->context, handle, {opcode}, buffer, sizeof(buffer), &bytes, info);",
                             "if (result) return result;",
                             f"return {message_type}_decode(buffer, bytes, message);"]
                functions.append((operation, parameters, "coord", body, "Nonblocking typed coordination; identity is managed by the runtime."))
        for operation, parameters, callback, body, description in functions:
            signature = f"micros_result_t {prefix}_{operation}({parameters})"
            declarations += [f"/** @brief {description} */", signature + ";"]
            implementation += [signature, "{",
                f"    if (!args || !args->api || !args->api->_ipc || !args->api->_ipc->{callback})",
                "        return MICROS_ERROR_UNSUPPORTED;",
                *["    " + line for line in body], "}"]
    from micros_tooling.config.coordination_codegen import callback_artifacts
    callback_header, callback_source = callback_artifacts(name, ports)
    declarations += callback_header
    implementation += callback_source
    # Let transport services open their declared ports without inspecting private IPC.
    header += [f"#define {name.upper()}_IPC_PORT_COUNT {len(ports)}u",
               f"#define {name.upper()}_IPC_PORTS(X) " + " ".join(
                   f"X({index}, {name}_{port['name']})" for index, port in enumerate(ports))]
    header += ['#ifdef __cplusplus', 'extern "C" {', '#endif', *declarations,
               '#ifdef __cplusplus', '}', '#endif', '#endif', '']
    implementation.append('')
    return "\n".join(header), "\n".join(implementation)
