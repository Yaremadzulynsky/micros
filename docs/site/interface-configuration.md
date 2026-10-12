---
title: Interface file reference
---

# Interface file reference

**Location:** chosen by your project, for example
`protos/reading/interface.toml` beside `reading.proto`. An interface describes the
message and delivery policy used by a service port. It does not choose which
services run; the [unit](unit-configuration.md#channels) does that.

## Complete message and interface

Create `protos/reading/reading.proto`:

```protobuf
syntax = "proto3";
message Reading {
  uint32 value = 1;
}
```

Beside it, create `protos/reading/interface.toml`:

```toml
[interface]
interface = "example.reading"
schema = "reading.proto"

[delivery]
policy = "latest"
```

These files define a message contract. To actually send/receive values, implement
service behavior and add the service ports and unit channel shown below.

## Fields

| Section / field | Required / default | Meaning |
| --- | --- | --- |
| `[interface].interface` | Required string | Message contract identity, such as `example.reading` |
| `[interface].schema` | Required path | Protobuf file, relative to this interface file |
| `[interface].max_payload` | Default: computed encoded maximum | Optional byte capacity, at least the computed maximum and at most 256 |
| `[delivery].policy` | Required | `latest` or `stream` |
| `[delivery].kind` | Optional; ordinary channel when omitted | Advanced coordination kind: `state`, `event`, or `action` |

Modern interfaces require the `[delivery]` table. Do not author major/minor
versions or `accepts_minor`: connected endpoints require matching interface
identity and schema. Service-local named types are not shared message schemas.

## Choose a delivery policy

| Policy | Retains | Channel depth | Consumer behavior |
| --- | --- | --- | --- |
| `latest` | Most recent message | Exactly 1 | Intermediate values may be skipped |
| `stream` | Bounded sequence of messages | 1–8 | Slow consumers can lose messages; handle the loss indication |

For stream delivery, change the interface's policy to `"stream"`. The unit can
choose `depth = 4` or another valid capacity meeting all port minima. Policy stays
in the interface so producers and consumers cannot silently disagree.

Payload bounds come from the protobuf schema. Unbounded variable-length data
needs explicit bounds accepted by the [protobuf tooling](../../src/micros_tooling/config/protobuf.py);
start with the scalar example above. `max_payload` cannot make an oversized schema
fit. The encoded maximum is a storage bound, not a sampling interval or throughput
promise.

## Connect a producer and a consumer

In `services/sensor/service.toml`, add this fragment:

```toml
[service.publications.reading]
interface = "../../protos/reading/interface.toml"
```

In `services/display/service.toml`, add:

```toml
[service.subscriptions.reading]
interface = "../../protos/reading/interface.toml"
```

In the unit selecting both services, add:

```toml
[channels.reading]
```

The matching name `reading` attaches both ports. Each service also needs its own
identity, build definition, and implementation. This is wiring configuration,
not supplied sensor/display code. The [connection walkthrough](connect-service-ports.md)
covers generation and the callbacks you implement.

A port may add `min_depth = 4` if it requires stream retention. An explicit unit
depth below that minimum fails validation. A channel with no enabled port also
fails validation. Distinct message groups need distinct channel names.

## Advanced coordination

`kind = "state"`, `"event"`, or `"action"` requires `policy = "latest"` and
payload capacity no greater than 64 bytes. Coordination ports currently require
the manual coordination adapter; hook lifecycle services cannot use them.
Leave `kind` out for ordinary publisher/subscriber messaging. See
[Coordination](coordination-reference.md) before choosing this option.

## Validate

```sh
./micros generate
./micros compose -d host
```

For board wiring, substitute `-d HARDWARE_ID`. Generation checks the referenced
schemas; composition checks the enabled service endpoints and chosen channel
depths together. Neither command sends messages or validates physical behavior.
