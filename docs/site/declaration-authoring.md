---
title: Declarations
hide:
  - toc
---

<span class="docs-editorial"></span>

Reference · Declarations
{: .arch-eyebrow}

# Declarations

A service contract owns types and requirements. A unit owns physical choices.
Generated C and metadata are build output. This page documents current-dev TOML;
[legacy composition](configuration-reference.md) is separate.
{: .arch-intro}

## 01 · File ownership {#file-ownership}

| File | Owns |
| --- | --- |
| `services/NAME/service.toml` | Build inputs, types, config defaults, pins, timers, ports, commands |
| `units/HARDWARE_ID.toml` | Hardware ID, board, selected services, config values, pin assignments, channels, exposure, budgets |
| Shared `interface.toml` and `.proto` | Message identity, delivery policy, fields and wire tags |

Contract source paths are relative to the contract; unit source paths are relative
to the unit. `contract = "service.toml"` resolves inside its `source` directory.
`build.api` is a stable C identifier independent of the instance alias.
Multiple instances need distinct deployed names. Interfaces and codecs are generated
under `build/services/`; physical bindings live under `build/units/`.

## 02 · Settings and reusable types {#settings-and-reusable-types}

```toml
# service.toml
[service.types.Brightness]
type = "uint32"
min = 0
max = 255

[service.config]
brightness = { type = "Brightness", default = 8 }

[service.commands.set_brightness]
args = { brightness = "Brightness" }
returns = { brightness = "Brightness" }
```

The unit selects `config = { brightness = 32 }` in that service's table.
Omitted values use service defaults; values remain fixed for a service lifetime.
Startup settings support `uint32` and `enum`; commands have additional types
listed in [Service commands](service-commands.md). Type references cannot override
bounds. Enum order is numeric identity, so reordering can change behavior.

Larger service-local types can live in a `types.toml` selected by the service's
`types` field. The file must stay within that service directory. Use inline types
or that file, not duplicate definitions. Types in another service are independent;
shared messages use explicit interface references.

## 03 · Pins and timers {#pins-and-timers}

```toml
# service.toml
[service]
pins = { button = { type = "pullup" }, temperature = { type = "analog" } }
timers = ["sample"]
```

```toml
# unit file
[services.sensor]
source = "../services/sensor"
contract = "service.toml"
pins = { button = 38, temperature = 34 }
memory = { arena = "RAM", stack_bytes = 4096 }
```

This is a declaration example; choose actual pins using `./micros pins --all`
and your board's wiring. Supported types are `input`, `pullup`, `pulldown`,
`output`, and `analog`. Every role needs one assignment. Reserved pins, physical
conflicts, unsupported types, and driver `fixed_pin` violations fail validation.
Disabled new-style services allocate no pins.

Pull requirements need verified board bias or supported runtime configuration;
the current ESP32 graph cannot encode internal pulls. Analog input requires an
available ADC1 mapping and returns raw 12-bit counts with the ABI's 12 dB
attenuation, not calibrated voltage. Exact target capabilities are in
[chip/board definitions](../../config/README.md).

Named timers reserve handles, not schedules. Code chooses delay, period, and
callback using the generated timer helper. Hook lifecycles close these handles;
manual ABI lifecycles own their cleanup. See [Write a service](write-a-service.md).

## 04 · Channels {#channels}

[Connect services](connect-service-ports.md) is the complete same-name port/channel
example. The shared interface owns protobuf and delivery policy. The unit declares
channel names and optional depth, not copies of schema, policy, keys, or versions.
Enabled ports attach by name; unrelated groups need distinct names.

Composition rejects mismatched schema or delivery requirements. It derives bounded
payload capacity and deterministic numeric keys in sorted channel-name order.
Those keys are release-local, not stable external addresses. An explicit depth
below a connected minimum fails; omitted depth uses the greatest minimum (default 1).
`latest` always requires depth 1. Plain channels permit multiple publishers and
subscribers; coordination has its additional endpoint limits.

## 05 · Limits and validation {#limits-and-validation}

| Current format ceiling | Limit |
| --- | --- |
| Services, including bridges | 4 |
| Local channels | 4 |
| Stream depth | 8 messages |
| Encoded local message | 256 bytes |
| Handles per service | 8 |
| Encoded startup configuration | 256 bytes |

Target/base admission can be tighter. Arena, stack, executable image, and shared
channel storage are separate budgets; see [Service API](service-api.md#resources)
and [package compatibility](packages-and-storage.md).

```sh
./micros generate
./micros compose
./micros contract-diff units/HARDWARE_ID.toml --base HEAD
```

`generate` needs no board; `compose` validates the unit offline. Neither executes
service behavior. `contract-diff` reads an explicit Git baseline; external SDK
references use the current dependency checkout, so compare SDK changes there.

Legacy `config_schema`, hardware/timer tables, and keyed channels remain readable;
do not mix old and new definitions of the same setting/resource. Command metadata
format 2 requires compatible CLI/server readers; update those before deploying it
to an older server. Source validators: [declarations](../../src/micros_tooling/config/declarations.py),
[service contracts](../../src/micros_tooling/config/service_contract.py), and
[packages](../../src/micros_tooling/storage/packages.py).
