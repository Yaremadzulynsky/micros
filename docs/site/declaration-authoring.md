---
title: Configuration reference
---

# Configuration reference

Start with **the file you want to change**. Each setting has one owner: the
service defines what it needs, the unit chooses where and how it runs, and a
shared interface defines messages exchanged by services.

Field references: [Service definitions](service-configuration.md) ·
[Unit files](unit-configuration.md) · [Shared interfaces](interface-configuration.md).

## Which file do I edit? {#file-ownership}

| I want to… | Edit | Reference |
| --- | --- | --- |
| Change the sample interval on this host or board | `units/host.toml` or `units/<hardware-id>.toml` → `services.climate_sensor.config` | [Unit settings](unit-configuration.md#settings) |
| Change the interval's default or allowed range | `services/climate-sensor/service.toml` → `service.config_schema.interval_ms` | [Service settings](service-configuration.md#settings) |
| Add C/C++ source files or compiler definitions | `service.toml` → `service.build` | [Build options](service-configuration.md#build) |
| Declare a timer, pin role, or command | `service.toml` | [Service reference](service-configuration.md) |
| Choose a physical pin, select a service, or expose a command | Board unit | [Unit reference](unit-configuration.md) |
| Define a message and whether a channel keeps the latest value or a stream | `interface.toml` and its `.proto` | [Interface reference](interface-configuration.md) |
| Connect services using that message | Service ports + a same-name channel in the unit | [Complete connection example](connect-service-ports.md) |

A generated project starts with:

```text
my-application/
  services/climate-sensor/
    service.toml              requirements, build inputs, setting defaults
    src/service.c             behavior
  units/
    host.toml                 local services and selected settings
    <hardware-id>.toml        added after successful board enrollment
  micros.lock                 pinned SDK revision
```

The starter also includes fan-controller and status-display services, with shared
protobuf contracts under `protos/climate/` and `protos/fan/`.
Each physical board has its own complete unit and deploys independently.

## Generate C/C++ APIs {#generate-code}

From the application root, regenerate after editing service or interface declarations:

```sh
./micros generate
# Or regenerate one service:
./micros generate --service services/climate-sensor
```

The generator reads each `services/*/service.toml`, its referenced
`protos/*/interface.toml` and `.proto` files. It writes the matching headers,
protobuf codecs, resource bindings and hook lifecycle code under
`build/services/SERVICE_DIRECTORY/generated/`. For the climate sensor, inspect
`build/services/climate-sensor/generated/climate_hooks.h`, `climate_config.h`
and `climate_ipc.h` there. The command prints the generated directory for each service.

Write behavior in `services/*/src/`; generation does not invent the sensor driver
or fan policy and does not overwrite those source files. Do not edit generated
files: the next generation replaces them. Unit TOML selects settings, service
instances and channels; `./micros compose -d host` validates that assembled
application. Generation does not build or deploy it. [Run locally](run-locally.md)
or [deploy to an enrolled board](deploy-an-application.md) to execute the code.

## One setting, from declaration to behavior {#settings-and-reusable-types}

In `services/climate-sensor/service.toml`, define what values are valid:

```toml
[service.config_schema.interval_ms]
type = "uint32"
default = 1000
min = 100
max = 60000
```

In `units/host.toml`, select this host instance's value:

```toml
[services.climate_sensor]
source = "../services/climate-sensor"
contract = "service.toml"
memory = { arena = "RAM", stack_bytes = 4096 }
config = { interval_ms = 250 }

[channels.climate_reading]
```

The generated C context provides `ctx->config.interval_ms`. The climate service uses it when
opening its timer. Omitting `config.interval_ms` selects `1000`; choosing `50`
fails validation before deployment. A setting does not implement behavior by
itself, and editing TOML does not change an already-running service.

The service uses **`config_schema` for definitions**; the unit uses **`config` for
values**. Use these names consistently. The references below describe the current
project format, without alternative migration syntax.

## How paths and names work

| Written in | Example | Resolved from |
| --- | --- | --- |
| Unit `source` | `../services/climate-sensor` | Directory containing the unit: `units/` |
| Unit `contract` | `service.toml` | The selected `source` directory |
| Service `build.sources` | `src/service.c` | Service source directory |
| Service `types` | `types.toml` | Directory containing `service.toml`; must stay inside it |
| Service port `interface` | `../../protos/reading/interface.toml` | Directory containing `service.toml` |
| Interface `schema` | `reading.proto` | Directory containing `interface.toml` |

`climate_sensor` in `[services.climate_sensor]` is the unit's **instance alias**. `example.climate-sensor` in
`[service].name` is its **deployed service name**. `climate` in `[service.build].api`
is the **generated C prefix**. They serve different purposes; see
[multiple instances](unit-configuration.md#instances) before selecting one service twice.

TOML tables keep their scope until the next table header. Put `timers` under
`[service]`, not below `[service.build]`. Do not repeat a table or key to override
it: edit the existing declaration. A line beginning with `#` is a comment.

## Pins and timers {#pins-and-timers}

A service declares pin **roles** and timer **names**. A board unit assigns actual
pin numbers. The implementation opens timers with a delay and period.

See [pin and timer fields](service-configuration.md#pins-and-timers) and
[unit wiring](unit-configuration.md#pins). GPIO requires a physical board;
`units/host.toml` runs services that do not require it.

## Ports and channels {#channels}

A service publishes or subscribes to a named port. Its referenced interface owns
the protobuf message and delivery policy. The unit declares a channel with the
same name. No separate endpoint-binding list is needed.

See [interface fields](interface-configuration.md) for the reference and
[Connect services](connect-service-ports.md) for the step-by-step example.

## Validate the file you changed {#limits-and-validation}

Run from the application root:

```sh
./micros generate --service services/climate-sensor  # Validate and generate service APIs
./micros compose -d host                   # Validate the complete host unit
./micros compose -d HARDWARE_ID            # Validate one enrolled board unit
./micros test -k settings                  # Run the starter's behavior test
```

Generation and composition are offline. Composition checks declarations and
bindings; it does not prove that hardware works. `deploy --dry-run` additionally
builds and checks against the selected board's base and live state; it requires
a connection. Only deployment changes the running application.

Before enrollment, `compose` defaults to the host. With one board it defaults to
that board; with multiple boards select one explicitly. `-d host` is always explicit.

| Runtime/package ceiling | Limit |
| --- | --- |
| Services, including command bridges | 4 |
| Channels, including command transport channels | 4 |
| Stream depth | 8 messages |
| Encoded channel message | 256 bytes |
| Handles per service | 8 across timers, GPIO and port endpoints |
| Encoded startup settings | 256 bytes |

These are ceilings, not guaranteed free capacity. Target/base admission may be
tighter. Command exposure has [additional transport costs](service-commands.md#transport-budget).
Stack reservations, service arena memory and channel storage are different
budgets; see [unit memory](unit-configuration.md#memory).

## Common mistakes

| Symptom | What to check |
| --- | --- |
| Source or contract cannot be found | A unit in `units/` normally uses `source = "../services/NAME"`. |
| Unknown setting | Put defaults/types in the service's `config_schema`; put selected values in the unit's `config`. Check the table containing the key. |
| Value outside bounds | Change the selected value, or deliberately change the service's declared bounds. |
| Required channel is not declared | Add `[channels.PORT_NAME]` to the unit for every enabled service port. |
| Channel has no enabled service port | Remove the unused channel or enable a service with a matching port name. |
| Pin requirements do not match | Assign every declared role exactly once; inspect `./micros pins -d HARDWARE_ID --all`. |
| A new command is unavailable remotely | Add its handler, select it in `expose_commands`, and deploy the changed unit. |
| Generated C mentions a missing callback | Implement the new hook shown by `./micros scaffold-service services/climate-sensor --preview`. Generation does not write application behavior. |

The field references are checked against the [service parser](../../src/micros_tooling/config/declarations.py),
[unit loader](../../src/micros_tooling/config/configuration.py), and
[channel resolver](../../src/micros_tooling/config/unit_model.py).
