# Ipc

> Historical architecture discussion and milestone resolutions. The [V1 architecture](../../v1-architecture.md) and [implemented feature matrix](../V1.md) take precedence over original proposals below.

Status: Working architecture. Original direction and review proposals are preserved below. The M0 contract, where present, takes precedence for the initial implementation; other proposals remain unaccepted.

## 8. IPC: Protobuf-Only Service Communication

Services do **not** exchange shared pointers.

All service-to-service communication goes through micros IPC and uses **Protocol Buffers** for message serialization.

The kernel does not need to understand application protobuf fields. At the kernel level, a message payload is opaque bytes plus metadata.

```text
Service A
   │
   │ protobuf
   ▼
┌───────────────┐
│ micros IPC Bus│
└───────────────┘
   │
   │ protobuf
   ▼
Service B
```

This replaces the earlier idea of using an MQTT broker for local IPC. MQTT may still be useful at a network boundary, but is unnecessary overhead for communication entirely inside one micros instance.

---

## 9. Channels and Manifests

Channels are **not compiled into the kernel**.

A service declares its communication contract in its manifest. This allows schemas and services to evolve without requiring an OS update.

Conceptually:

```yaml
name: imu-driver
version: 1.2.0
abi_version: 1

memory:
  runtime_bytes: 32768
  stack_bytes: 4096

capabilities:
  - spi
  - gpio
  - timer

publishes:
  - channel: imu.samples
    schema: ImuSample
    schema_hash: ...
    policy: stream
    depth: 64

subscribes:
  - channel: vehicle.command
    schema: VehicleCommand
    schema_hash: ...
```

The exact manifest format is not decided; YAML above is illustrative.

At boot/load time, micros can use manifests to:

1. Check ABI compatibility.
2. Determine memory requirements.
3. Validate hardware capabilities.
4. Construct the IPC communication graph.
5. Validate publisher/subscriber compatibility.
6. Allocate channel buffers.
7. Reject configurations that cannot fit.

The kernel moves bytes; manifests and deployment tooling describe what those bytes mean.

---

## 10. IPC Stream Ring Buffer

For streaming data, use a **kernel-owned bounded circular buffer**.

Every published message receives a monotonically increasing sequence number.

Conceptually:

```text
Channel: imu.samples

           oldest                       newest
             ↓                             ↓
      ┌──────┬──────┬──────┬──────┬──────┐
      │ #104 │ #105 │ #106 │ #107 │ #108 │
      └──────┴──────┴──────┴──────┴──────┘
                                      ↑
                              writer sequence
```

Subscribers do **not** advance a global read pointer.

Each subscriber tracks its own sequence position:

```text
Service A last_seen = 108
Service B last_seen = 105
Service C last_seen = 107
```

Reading from the channel asks for the message after the subscriber's last sequence.

This means Service A consuming a message cannot cause Service B to lose its position.

### Slow Subscriber / Overwrite Semantics

The writer must not be permanently blocked because a consumer is slow or dead.

If the ring has advanced far enough that a subscriber's expected message has already been overwritten:

```text
subscriber expects: #101
oldest available:   #104
```

micros explicitly reports a missed-data condition, conceptually:

```c
IPC_RESULT_MESSAGES_MISSED
```

The subscriber can then choose how to recover: jump to the newest sample, restart processing from the oldest retained sample, request state again, or take application-specific action.

**Failure is explicit rather than silently pretending delivery succeeded.**

This makes streams bounded and prevents one failed service from blocking the whole IPC system.

---

## 11. IPC Delivery Policies

Not every message has identical semantics. Channels should declare a delivery policy.

Initial candidates:

### `stream`

Bounded ordered history. Uses sequence numbers and detects missed messages.

Good for telemetry, IMU samples, logs, etc.

### `latest`

Only the newest value matters.

Good for state such as:

```text
current temperature
current position
current setpoint
```

A slow reader does not need historical values.

### `event`

Represents discrete occurrences where event semantics matter.

Exact reliability/overflow semantics remain to be specified.

The kernel should implement generic channel mechanisms rather than application-specific topics.

---

## 12. Protobuf Schema Evolution

A protobuf schema change should **not require an micros kernel update**.

Schemas belong to service interfaces.

Backward-compatible protobuf changes, such as adding optional/new fields appropriately, can allow old and new services to coexist.

For breaking changes, deployment tooling should inspect manifests/schema identifiers and reject incompatible single-service upgrades.

Conceptually:

```text
install service X v2
        │
        ▼
read manifest/schema dependencies
        │
        ├── compatible -> install
        │
        └── incompatible -> reject and identify dependent services
```

Compatibility checking is primarily a **deployment/package-management responsibility**, not kernel application logic.

---

## 13. Distributed IPC

Local IPC and network communication should eventually share the same service-facing abstraction.

A bridge service can subscribe to selected local channels and forward their protobuf messages to another micros instance.

```text
 ESP32 A                               Computer / ESP32 B

 Service A                                 Service B
    │                                          ▲
    ▼                                          │
 Local IPC                                    Local IPC
    │                                          ▲
    ▼                                          │
 Bridge ───── TCP / QUIC / LoRa / ... ───── Bridge
```

The application service should not need to care whether its peer is local or remote.

The network transport remains replaceable. The IPC abstraction should not be tied to MQTT, TCP, QUIC, LoRa, or any single transport.

---

### 19.6 IPC Contract Details

**Established direction:** kernel-owned bounded channels, independent subscriber positions, explicit stream loss, and no shared service pointers.

**Open:** synchronization and precise operation semantics.

Before implementation, define:

- Single or multiple publishers per channel and publication ordering.
- Atomic publication and protection against reading partially overwritten messages.
- Maximum encoded payload length and oversized-message rejection.
- Blocking, nonblocking, timeout, and wakeup behavior.
- Whether missed-data results include a message and how cursors advance.
- Subscription start position and behavior when publishers stop.
- Sequence exhaustion and channel recreation behavior.
- Whether channel memory survives individual service restarts.

**Proposal:** identify a channel instance with a generation identifier in addition to message sequence numbers, so stale subscriptions cannot mistake a recreated channel for its previous instance.

Caller-owned buffers may be used for synchronous SDK copies without establishing shared service memory. The ABI must define when a buffer can be reused.

**Proposal:** implement `stream` and `latest` first. Defer `event` until overflow, acceptance, acknowledgements, retries, and duplicate handling have explicit semantics. A successful publish must not imply that a subscriber processed or acted on the message.

### 19.7 Schema Identity and Compatibility

**Established direction:** protobuf is the service communication format; compatibility belongs primarily to deployment tooling.

Schema hashes identify schemas; they do not establish compatibility. Different schemas may be wire-compatible, and wire-compatible changes can still alter application meaning.

**Proposal:** record schema identity separately from the declared interface compatibility version. Define canonical hashing inputs and compatibility rules in the deployment tooling specification. Interface definitions must document units, ranges, presence/default semantics, and other behavioral requirements that wire checks cannot establish.

Because the kernel treats payloads as opaque bytes, protobuf-only communication is an SDK and service-interface contract unless additional validation is implemented. Receivers must validate incoming data and bound decoded resources as well as encoded message size.


## M0 Demo Contract

The first graph is a synthetic sensor publisher and a logger consumer, developed on the host in M3 and moved to the MCU in M5. Hardware readings replace the synthetic source only after board/peripheral identification.

The button publisher emits `micros.button.v1.ButtonState { uint32 sequence = 1; uint64 monotonic_us = 2; bool pressed = 3; }` on `button.state` after confirming a debounced state. The transport test fixture uses the same contract with alternating synthetic button states at 10 Hz. Nanopb generates the bounded C codec from this proto; typed port functions serialize/deserialize internally. Tests check it against the reference protobuf implementation using the same schema.

The graph uses one publisher, a stream depth of 8, and maximum encoded payload 64 bytes. Run a second subscriber and deliberately pause one to force explicit loss reporting while the other continues. These are demo configuration values, not global kernel defaults. Service-to-service data remains protobuf; the kernel debug-write API used in M1 is not this IPC path.

Channel synchronization, complete operation signatures, and encoding-library selection remain M3 work. Reliable event policy and distributed transport remain deferred.

## M3 Implementation Resolution

[ADR 0006](decisions/0006-bounded-ipc.md) and the [M3 record](../milestones/M3.md) resolve stream/latest synchronization, loss/cursor semantics, channel generations, bounded protobuf encoding, and the host demo. Their implemented contract supersedes the earlier proposals. Package/schema compatibility admission follows in M4.
