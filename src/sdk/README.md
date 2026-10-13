# Service SDK

Service message types and codecs are generated from `src/sdk/protos/` by pinned Nanopb.
`./micros generate` writes `.pb.h`, `.pb.c`, `.codec.h` and typed IPC bindings into
each participating service's `generated/` directory. The shared C runtime lives
in `src/third_party/nanopb/`; `c/src/freestanding.c` supplies compiler-required byte copies.
There is no hand-maintained ButtonState codec or duplicate C message definition.

Use the generated port functions to publish/read typed messages. The SDK serializes
protobuf bytes into TOML-bounded buffers, validates incoming protobuf and preserves
output on decoding errors. Public service code has no raw IPC dispatch operations.
See [the SDK guide](../../docs/archive/documentation/SDK.md) for source structure and supported message bounds.
