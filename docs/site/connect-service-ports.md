---
title: Connect services
hide:
  - toc
---

<span class="docs-editorial"></span>

Build · Connect services
{: .arch-eyebrow}

# Connect services

Services exchange typed messages through named, bounded channels. Each subscriber
has its own read position; one reader does not consume another's message.
{: .arch-intro}

## Start with the working example {#starter-flow}

`micros new` already creates a complete, hardware-independent message flow:

```text
climate-sensor → climate_reading → fan-controller → fan_status
                         └─────────────┬──────────────┘
                                 status-display
```

The sensor calls `src/simulated_sensor.c` on a timer. Both consumers independently
read the same climate channel; the display also reads the fan decision. The
protobuf messages under `protos/climate/` and `protos/fan/` carry bounded numeric
fields, sample IDs and timestamps. Both channels use `latest` delivery.

Run `./micros generate`, `./micros compose -d host` and `./micros test` from the
[starter project](get-started.md#create-your-project). Read its service sources
and generated `climate_ipc.h`, `fan_ipc.h` and `display_ipc.h` under `build/services/`.
The following sections show how to add another message contract to your own services.

## 01 · Define one shared message {#define-one-shared-message}

In your project, create `protos/reading/reading.proto`:

```protobuf
syntax = "proto3";
message Reading {
  uint32 value = 1;
}
```

Beside it, create `interface.toml`:

```toml
[interface]
interface = "example.reading"
schema = "reading.proto"

[delivery]
policy = "latest"
```

In the producer's `services/sensor/service.toml`, add:

```toml
[service.publications.reading]
interface = "../../protos/reading/interface.toml"
```

In the consumer's `services/display/service.toml`, add:

```toml
[service.subscriptions.reading]
interface = "../../protos/reading/interface.toml"
```

These are additions to complete [service contracts](write-a-service.md), not
implementations of a sensor or display. Select both services in your unit and add:

```toml
[channels.reading]
```

The same-name ports attach to this channel. Its contract and payload capacity are
derived from the shared interface. Exact protobuf compatibility is checked; the
current format does not author major/minor versions.

## 02 · Generate and implement {#generate-and-implement}

```sh
./micros generate
./micros compose -d host
```

For a board unit, replace `host` with its hardware ID.

Read each generated `API_ipc.h` for the actual type and operation names. A manual
service opens the generated publication/subscription, publishes or reads typed
messages, and closes the handle. Hook services receive generated port handles and
subscription callbacks; application code still publishes values explicitly.
Use `scaffold-service --preview` for the current hook signatures.

The [clock and LED tutorial sources](../../examples/tutorials/toggle/README.md)
show hook-based publication and subscription. The manual
[DHT source](../../examples/services/dht/src/service.c) shows explicit publication
and cleanup with an ESP32-specific hardware driver. TOML alone does not implement
message production or consumption.

## 03 · Choose retention {#choose-retention}

| Policy | Retains | Reader behavior |
| --- | --- | --- |
| `latest` | Newest value, depth 1 | Intermediate values can be skipped. |
| `stream` | Bounded sequence | A slow reader can lose messages. |

For a stream, change `[delivery].policy` in the shared interface and select a
unit depth, for example `[channels.reading]` with `depth = 8`. A subscriber may
require `min_depth`; a smaller explicit unit depth is rejected.

Manual reads return `MICROS_ERROR_EMPTY` when there is no unread value.
`MICROS_ERROR_MESSAGES_MISSED` reports a stream gap and returns no message on that
call; handle the gap, then read again. Generated hook services receive their loss
callback. Sequence/loss metadata is per subscriber.

Successful publication means bytes were copied, not that another service acted.
Add timestamps/validity to your own schema if freshness matters. Separate channel
reads are not an atomic snapshot, and retained messages are not automatically new
actions after restart.

For a network boundary, use [Coordination](coordination-reference.md). For remote
visualization, use [Service channels](inspect-service-channels.md); capture and coordination
have distinct declarations and resource costs.
