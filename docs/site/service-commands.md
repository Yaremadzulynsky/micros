---
title: Service commands
hide:
  - toc
---

<span class="docs-editorial"></span>

Build · Service commands
{: .arch-eyebrow}

# Service commands

Declare commands in a service contract, implement their hooks, and expose selected
commands in the unit. [Write a service](write-a-service.md) contains a complete
counter example; no handwritten protobuf or presentation metadata is needed.
{: .arch-intro}

## 01 · Declare and expose {#declare-and-expose}

```toml
# service.toml
[service.commands.increment]
returns = { count = "uint32" }
```

```toml
# Within the unit's selected service table
expose_commands = ["increment"]
```

Omitted/empty exposure lists expose nothing. `args` and `returns` default to empty
tables. An empty result still reports handler completion. Use
`build.lifecycle = "hooks"` and `scaffold-service` for the current workflow.

| Field type | Example |
| --- | --- |
| Unsigned integer | `"uint32"` |
| Bounded signed integer | `{ type = "sint32", min = -10, max = 10 }` |
| Boolean | `"bool"` |
| Bounded UTF-8 string | `{ type = "string", max_bytes = 32 }` |
| Service-local named type | `"Color"` |
| Enum | `{ type = "enum", choices = ["red", "blue"] }` |

Strings require a bound and cannot contain NUL. See [Declarations](declaration-authoring.md)
for reusable types. Generated headers are the authority for C hook signatures.
Handlers return `MICROS_OK` with populated outputs or a `MICROS_ERROR_*` result.
They run on the service worker and must finish in bounded time.

## 02 · Transport budget {#transport-budget}

Each exposed service adds request and response streams and shares a network-bridge
service with other exposed services. This consumes **two channels per exposed service**
and a bridge slot. Channels have depth 4 and 112-byte capacity including the envelope;
generation rejects an oversized worst-case protobuf. The format ceilings are
[listed once in Declarations](declaration-authoring.md#limits-and-validation).

Command schemas permit eight commands, eight fields per argument/result table,
32 named types, 1–64 UTF-8 bytes per string, and 1–32 enum choices. Exact
validation lives in the [command implementation](../../src/micros_tooling/commands/schema.py).

The current transport supports ESP32 bases with authenticated IPC bridging and
boot/service instance identities. Update the CLI and server for command metadata;
a base lacking the required identity support rejects calls.

## 03 · Call and interpret the result {#call-and-interpret-the-result}

After deployment, open [the shell](interactive-shell.md):

```text
commands
help call example.counter increment
call example.counter increment
```

All declared arguments are required. Use `FIELD=VALUE`, quote strings with spaces,
and use enum names or `true`/`false` for booleans. Completion means the handler
returned successfully; it is not independent evidence of a physical effect.

Errors return a failed result. Disconnects, lost replies, or interrupted waits can
leave an **unknown** outcome. Writes are not automatically retried; Ctrl-C stops
waiting but may not stop a dispatched handler. Inspect state before repeating a
physical action. Request deduplication is not durable exactly-once execution.

Legacy manual lifecycle handlers remain supported in the
[typed-command example](../../examples/typed-commands/README.md). Their
`scaffold-commands` and schema assertions are not required by the hook workflow.
