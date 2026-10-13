# Shared protobuf messages

Shared protobuf message definitions live here, organized by contract and major version. `button/v1/button_state.proto` defines the ButtonState message shared by the button publisher and its subscribers. Channel settings belong to the consuming application's recipe. Button semantics are documented in [the button example](../../../examples/services/button/README.md).

`micros.toml` defines each channel under `[channels.NAME]`, including its protobuf schema path and transport bounds. Services refer to that alias through declared publication/subscription ports. The builder derives schema hashes and checks compatibility. Changing the shared contract must be coordinated with all consumers.

Service startup configuration is distinct from IPC messages. Its typed definitions live under `[services.NAME.config_schema]` in `micros.toml`; see [configuration](../../../docs/archive/documentation/CONFIGURATION.md).

`./micros generate` compiles these files using pinned protoc and Nanopb, producing
service-local types, codecs and typed port functions. Declare one top-level message
per channel schema; nested messages are allowed. Put static bounds inside the proto
with Nanopb options rather than a separate options file. Message imports are not yet
supported. See [the SDK guide](../../../docs/archive/documentation/SDK.md) for examples and limits.

Button interface minor 1 adds `publisher_started_us`, a nonzero monotonic publisher epoch. Consumers resynchronize on a new epoch, rather than treating a legitimate restart as corrupt sequence ordering. The current application requires minor 1 on all button ports.
