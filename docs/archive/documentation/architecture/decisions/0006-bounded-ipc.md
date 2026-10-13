# ADR 0006 — Synchronous bounded channels and a scalar protobuf codec

Status: Accepted for M3. Date: 2026-09-05.

Use a single runtime publication lock with bounded synchronous copies for stream/latest channels. Independent subscriber cursors never gate writers. Stream loss advances to the oldest retained message and returns metadata without payload; a subsequent read delivers that message. Latest deliberately coalesces history. Capacity errors preserve cursors. Multiple publishers serialize in publication order.

Configured channels outlive individual services. Resource handles capture owner and channel generation; recreation invalidates registrations. Retire exhausted generations and stop before sequence/cursor wrap. Reserve fixed channel storage and count configured payload reservations separately.

Implement the small demo proto3 scalar schema with a bounded allocation-free codec, verified against Google's implementation. Unknown ordinary fields are skipped, malformed fields fail before unbounded work, and deprecated groups are unsupported. This avoids introducing a general generator/runtime before the first interface exists; schema growth may justify a generated bounded codec later.

Append IPC callbacks in experimental ABI revision 3. Keep the existing native descriptor and image envelope. The M1 firmware regression builds provide explicit unsupported stubs until M5.

Consequences: publication cannot expose torn messages or wait on a subscriber's cursor. A global lock serializes unrelated channels, appropriate to the small v1 profile; later throughput work can replace it while preserving these semantics. A successful write never claims delivery or application action. See the M3 milestone for evidence and exact limits.
