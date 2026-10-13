# Open Questions

> Historical architecture discussion and milestone resolutions. The [V1 architecture](../../v1-architecture.md) and [implemented feature matrix](../V1.md) take precedence over original proposals below.

The original questions are preserved here for traceability. Consult the decision index for current resolution status; items resolved by M0 no longer block M1.

## 17. Open Design Questions

The original questions were (many were subsequently resolved by M0–M8):

- Exact native service executable format.
- Whether to support ELF initially or define an micros-specific format.
- Relocation/linking strategy for independently compiled native services.
- Exact `ServiceDescriptor` ABI.
- Exact lifecycle function signatures.
- How native services bind/import micros SDK functions.
- Code-in-RAM versus execute-in-place strategy.
- Service package format.
- Manifest encoding.
- Capability representation and enforcement.
- Runtime memory allocator/region layout.
- Stack allocation and overflow detection.
- Exact IPC message header.
- Maximum/default protobuf payload size.
- Ring-buffer storage organization.
- Whether buffers are per-channel or backed by a common kernel pool.
- Exact semantics for `event` channels.
- Channel naming/ID strategy.
- Protobuf schema hashing/versioning rules.
- Deployment dependency-resolution rules.
- Remote IPC discovery and routing.
- Network bridge transport(s).
- Recovery partition sizing and exact boot state machine.
- Future kernel OTA strategy (explicitly deferred beyond v1).
- Hardware protection strategy on MPU/MMU-capable targets.

---


## Technical References


These references informed the review; platform details must be checked against the selected target and pinned SDK version before implementation.

- [Espressif: ESP32 memory types, ESP-IDF v4.4](https://docs.espressif.com/projects/esp-idf/en/v4.4/esp32/api-guides/memory-types.html) — instruction/data memory distinctions and execution placement; not a specification for every ESP32-family target.
- [Protocol Buffers: proto3 language guide](https://protobuf.dev/programming-guides/proto3/) — wire compatibility and schema evolution; wire safety does not establish behavioral compatibility.
