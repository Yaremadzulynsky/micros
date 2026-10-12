---
title: service.toml reference
---

# service.toml reference

**Location:** `services/NAME/service.toml`. This file describes reusable behavior:
its build inputs, settings, resource requirements, ports and commands. Select it
from a [unit file](unit-configuration.md) to run an instance.

The generated hello file includes commented examples. Only uncomment features
that your implementation uses; enabling a declaration can require new C hooks,
unit wiring, or shared interface files.

## Working hello definition

This complete declaration uses the source supplied by `micros new`:

```toml
[service]
name = "example.hello"
version = "1.1.0"
timers = ["greeting"]

[service.build]
api = "hello"
lifecycle = "hooks"
sources = ["src/service.c"]
descriptor = "micros_descriptor"

[service.config_schema.interval_ms]
type = "uint32"
default = 1000
min = 100
max = 60000
```

## Service identity

| Key under `[service]` | Required / default | Meaning |
| --- | --- | --- |
| `name` | Required string | Deployed service name, such as `example.hello`. A unit can override the name for a separate instance. |
| `version` | Required string | Three numeric components, such as `1.1.0`. |
| `timers` | Optional; none | Unique C identifier names, such as `["greeting", "sample"]`. |
| `types` | Optional; none | Inline named type tables, or a path to a service-local types file. Choose one form. |

All sections below belong to `[service]`. Unknown keys fail validation.
For C-facing names—API prefix, setting, timer, pin role, port, and command—use
lowercase names such as `sample_interval`, beginning with a letter. C keywords
are not permitted. Named types use `UpperCamelCase`, such as `ReadingCount`.

## Build inputs {#build}

| Key under `[service.build]` | Required / default | Meaning |
| --- | --- | --- |
| `api` | Required C identifier | Prefix of generated headers, context types, and hooks. Keep stable when changing an instance alias. |
| `sources` | Required nonempty list | Source paths relative to the service source directory. C and C++ files are supported. |
| `lifecycle` | Default `"manual"`; starter explicitly uses `"hooks"` | `hooks` generates lifecycle plumbing and resource cleanup. `manual` requires your ABI lifecycle implementation. |
| `descriptor` | Default `"micros_descriptor"` | Exported C descriptor symbol. Keep the starter value for generated hooks. |
| `defines` | Default `[]` | Compiler definitions without `-D`, e.g. `["VERBOSE=1"]`. |

To add a file or definition, edit the existing build table:

```toml
[service.build]
api = "hello"
lifecycle = "hooks"
sources = ["src/service.c", "src/format.c"]
defines = ["VERBOSE=1"]
descriptor = "micros_descriptor"
```

Create `src/format.c` before building. See [Service API](service-api.md) for
implementation rules; a declaration alone does not implement a service.

## Startup settings {#settings}

Each `[service.config_schema.NAME]` defines one setting. A unit selects its value
through `config = { NAME = VALUE }`. Values are fixed for that service instance's
lifetime; a running command's mutable state is a separate concept.

| Field | Required / default | Accepted values |
| --- | --- | --- |
| `type` | Required | `"uint32"`, `"enum"`, or a named type resolving to one of these |
| `default` | Required | Integer within bounds, or an enum choice string |
| `min` / `max` | Optional for inline `uint32` | Inclusive bounds; omitted ends default to `0` / `4294967295` |
| `choices` | Required for inline `enum` | 1–32 unique C identifier strings; `count` is reserved |

Partial additions to a service:

```toml
[service.config_schema.mode]
type = "enum"
choices = ["quiet", "normal", "verbose"]
default = "normal"

[service.config_schema.initial_count]
type = "Count"
default = 0
```

`Count` must be declared as below. Named references reuse their constraints; do
not add new `min`, `max`, or `choices` beside a named `type`. Enum order defines
its numeric identity. Startup settings do not accept signed integers, booleans,
or strings. Those kinds are available to commands.

## Reusable types {#types}

This optional table demonstrates every supported type kind:

```toml
[service.types]
Count = { type = "uint32", min = 0, max = 1000 }
Offset = { type = "sint32", min = -100, max = 100 }
Enabled = { type = "bool" }
Label = { type = "string", max_bytes = 32 }
Mode = { type = "enum", choices = ["quiet", "normal", "verbose"] }
```

| Kind | Constraints | Usable in |
| --- | --- | --- |
| `uint32` | Optional inclusive `min` / `max`, within 0…4294967295 | Settings and command fields |
| `sint32` | Optional inclusive `min` / `max`, within −2147483648…2147483647 | Command fields |
| `bool` | No extra fields | Command fields |
| `string` | Required `max_bytes`, 1–64 UTF-8 bytes; values cannot contain NUL | Command fields |
| `enum` | Required `choices`, 1–32 unique names | Settings and command fields |

At most 32 named types may be declared. Each named type defines a concrete kind;
chaining one named type to another is not supported.

For a larger library, replace the inline types with `types = "types.toml"` under
`[service]`, **before** the next table header. In `services/NAME/types.toml`, use
`[types]` instead of `[service.types]`. The referenced file must remain inside
this service directory. Types in other services are independent; shared messages
use [interfaces](interface-configuration.md).

## Pins and timers {#pins-and-timers}

Pin roles are optional. This is a declaration fragment, not assumed board wiring:

```toml
[service.pins.led]
type = "output"
# fixed_pin = 2

[service.pins.button]
type = "input"
```

| Pin field | Required / default | Meaning |
| --- | --- | --- |
| `type` | Required | `input`, `pullup`, `pulldown`, `output`, or `analog` |
| `fixed_pin` | Optional; unrestricted by the service | Driver constraint requiring that exact pin; currently 0–39. It is not a default assignment. |

The unit must [assign each role](unit-configuration.md#pins). Pulls need verified
external bias or supported runtime configuration; the current ESP32 runtime does
not configure internal pulls. Analog input requires an available ADC1 mapping.
Host units cannot use GPIO. Run `./micros pins -d HARDWARE_ID --all` before choosing
physical pins.

Declare named timers with `timers = ["greeting"]` under `[service]`. This reserves
a timer handle; C code chooses delay, period and callback using the generated
helper. Hook cleanup closes declared timers. Do not add timer intervals to TOML
unless they are actual settings that your code reads.

## Publications and subscriptions {#ports}

```toml
[service.publications.reading]
interface = "../../protos/reading/interface.toml"
min_depth = 1
```

A consumer declares `[service.subscriptions.reading]` with the same interface.
Port names must be unique across publications and subscriptions within a service.

| Port field | Required / default | Meaning |
| --- | --- | --- |
| `interface` | Required | Path to a shared `interface.toml`, relative to this service contract |
| `min_depth` | Default `1` | Minimum queue depth, 1–8; `latest` delivery requires 1 |

Policy, message schema, payload size and optional coordination kind belong in
the [interface](interface-configuration.md), not in the port. The unit needs a
same-name `[channels.reading]`. Use the [complete connection example](connect-service-ports.md)
to create all files and implement the producer/subscriber behavior.

## Commands {#commands}

This optional command uses the `Count` type defined above:

```toml
[service.commands.set_count]
description = "Set the counter value"
args = { value = "Count" }
returns = { value = "Count" }
```

| Command field | Required / default | Meaning |
| --- | --- | --- |
| `description` | Default: command name with underscores replaced by spaces | Help text, 1–80 characters |
| `args` | Default `{}` | Named input fields; at most 8, all required when called |
| `returns` | Default `{}` | Named output fields; at most 8 |

Field values may be a built-in type string (`"bool"`), a named type (`"Count"`),
or an inline type table (`{ type = "uint32", min = 0, max = 10 }`). Bounded strings
and enums need a named or inline definition. Empty arguments/results are valid.
At most 8 commands can be declared; names and field names are at most 48 characters.
Transport-reserved names such as `request_id`, `result`, and `command` are rejected.

Implement the generated command hook and select remote access in the unit's
[`expose_commands`](unit-configuration.md#commands). Declaring a command does not
expose it automatically. See [Service commands](service-commands.md) for the
transport budget and invocation workflow.

## Advanced: explicit capabilities {#capabilities}

Most services should omit this table: pins, timers and ports already declare their
resource requirements. For a manual ABI service with no named timers:

```toml
[service.capabilities]
timers = 1
gpio = []
```

`timers` is an integer count from 0–8; do not combine it with nonempty named timers.
`gpio`, when present, must list every declared pin role exactly once. Its default
is derived from the pin declarations. Handle counts are always derived; a
`handles` option is not accepted. This table does not open resources or implement
cleanup for a manual service.

## Validate

```sh
./micros generate --service services/climate-sensor
./micros scaffold-service services/climate-sensor --preview
./micros compose -d host
```

Use the first command after declaration changes, the second to inspect required
hook changes, and composition to check the selected unit's settings and bindings.
See the [configuration index](declaration-authoring.md) for limits and troubleshooting.
