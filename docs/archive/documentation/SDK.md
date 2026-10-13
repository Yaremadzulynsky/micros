# Service SDK reference

<span id="service-author-quickstart"></span>

For a guided path, [run the first application](../../site/first-application.md), then
[write a service](../../site/write-a-service.md). This page defines the implementation
contract and generated interfaces.


Build and run the [host demonstration](BUILDING.md) first. Start from the minimal C skeleton in `examples/hello-service/src/service.c` or its C++ counterpart in `examples/cpp-service/src/service.cpp`. The C example adds a one-second serial greeting timer; the C++ example contains only the lifecycle interface. Application implementations live in `services/`; timer/GPIO and protobuf test fixtures live in `tests/fixtures/`.

## The interface you implement

Include `micros/service.h` from `abi/include`. This is the shared service interface. A manually authored descriptor supplies all four hooks referenced by its `micros_service_descriptor_t`; host loaders also use the exported `micros_service_query`. The generated coordination adapter supplies the ABI hooks and descriptor for services using its callback interface, where application lifecycle callbacks are optional. A private header per tiny service is unnecessary: the public ABI declares the entry point and exact hook types. Application message contracts are separate `.proto` files owned by the service/interface.

The descriptor declares target profile, exact ABI major/revision, arena bytes/alignment, stack bytes and init/start/step/stop function pointers. Use `sizeof` and `alignof`/`_Alignof` for native state. It is a native pointer-bearing structure, distinct from the serialized image envelope. Keep reserved fields zero and the descriptor constant. Doxygen comments on the public types document the contract in editor hovers.

`init` receives an already zeroed, aligned arena and checked API table. Put per-instance state in that arena. `start` begins operation; `step` performs one bounded unit of work. Timers schedule callbacks on the same service worker, serialized with hooks. Never create private threads, block indefinitely, retain another service's pointers or bypass the managed lifecycle.

`stop` must handle partial initialization: close only handles you actually opened, cancel timers and release GPIO/IPC handles. The kernel also unwinds owned resources. It waits for callback quiescence and joins workers before reclaiming executable/data/arena/stack memory. An uncooperative hook or callback requires whole-runtime/device recovery; memory still reachable by a live worker is never recycled. V1's ordinary work deadline is 100 ms, a recovery policy rather than a hard-real-time guarantee.

Diagnostics, time, timer and GPIO operations use `args->api` with the supplied opaque context. IPC operations use service-local generated functions. Generation-aware handles reject stale and foreign references. Capabilities are declared in the package and enforced on API use; they do not sandbox trusted native memory accesses on ESP32. Never free the arena or retain it after stop/unload.

## Service source structure

`service.c` should make the service's general intent clear through its lifecycle hooks:
what it acquires, what starts, what input drives an action, and what it releases.
Keep that orchestration and its error handling beside the descriptor and query function.

Move state type definitions, configuration constants, lookup tables, decoding,
debouncing, formatting and hardware mechanics into focused private headers and source
files. Name helpers after their behavior so the lifecycle remains readable. Avoid
wrapping each hook in a generic helper that hides the entire flow. Small examples
need no extra files unless details obscure their purpose.

For example, the color service subscribes to button samples and opens the pixel in
`init`, displays its initial color in `start`, displays a new color after a debounced
press in `step`, and closes its resources in `stop`. Palette values, sample validation and pixel timing are implemented elsewhere.
Debouncing belongs to the button publisher; colors only detects confirmed press edges.

## Startup configuration

For composition, declare typed defaults and constraints in the reusable manifest
under `[service.config_schema]`, and choose values under `[services.NAME.config]`
in the application. The resolved unit stores both under `[services.NAME]`; directly
authored unit and standalone recipes use that same expanded format.
Generated service-scoped `*_config.h` headers provide types and decoders. Run
`./micros generate --project UNIT.toml` to place those headers in each service’s `generated/` directory for code completion without a firmware build. Decode `args->config_data` / `args->config_bytes` into arena state
in `init` before acquiring resources. Configuration is immutable through `stop`.
See [configuration strategy](CONFIGURATION.md) for encoding, overrides and migration.

## Data and messages

Write a proto3 schema with one top-level channel message. `./micros generate` invokes
pinned protoc and Nanopb to generate its C representation and codec. Nested messages,
enums and bounded repeated/string/bytes fields are supported; message imports are
not yet supported. Field bounds belong inside the proto using Nanopb options, for
example `import "nanopb.proto";` and `string label = 4 [(nanopb).max_size = 16];`.
Unbounded fields, callback/pointer allocation and a maximum encoded size exceeding
the channel's `max_payload` are rejected before existing generated files are changed.

Generated `.pb.h`/`.pb.c` files describe the wire representation. Generated `.codec.h`
files adapt the Nanopb codec to typed micros results. Port functions in `*_ipc.h` and
`*_ipc.c` allocate bounded stack buffers and encode/decode internally, without heap
allocation. Service code deals with typed messages, not byte buffers:

```c
// Button publisher: the type's fields come from ButtonState in the proto.
button_button_message_t message = {
    .sequence = ++state->sequence,
    .monotonic_us = confirmed_us,
    .pressed = state->debounce.stable_pressed,
    .publisher_started_us = state->publisher_started_us,
};
return button_button_publish(args, state->channel, &message);

// Colors subscriber: read also performs protobuf decoding.
colors_button_message_t message;
micros_result_t result = colors_button_read(args, subscription, &message);
```

A stream read can return EMPTY, CAPACITY or MESSAGES_MISSED. Loss advances to retained
history; the next read obtains a message. Errors, including malformed protobuf,
leave the destination message unchanged. Latest channels retain the newest value.
Publication success means the kernel copied protobuf bytes; no pointer to the
service's message is retained. Normal protobuf defaults and unknown-field handling
come from Nanopb. Tests compare generated codecs with Google's implementation using
descriptors compiled from the actual proto, with no mirrored field definitions.

Declare channel settings in `[channels.NAME]` in the application or directly authored unit and each service’s access in its `publications` or `subscriptions` tables. The builder derives schema hashes and generates the package manifest.

For example, `[services.colors.subscriptions.button]` with `channel = "button"` produces:

```c
#include "../generated/colors_ipc.h"

/* During init; store the returned handle in arena-owned state. */
return colors_button_open(args, &state->button.subscription);
```

That header also declares `colors_button_read` and `colors_button_close`. It exposes
no publish operation. Removing the subscription removes these declarations and makes
calls fail to compile. Run `./micros generate` after editing ports for IntelliSense;
`build` and `deploy` regenerate automatically. Generated implementations supply channel
keys, so do not hardcode them. Do not include the private SDK dispatch header or add
generated sources to `build.sources`.

Copy messages through IPC; do not communicate by sharing native addresses. GPIO resources come from the selected board definition and service grants. Use generated named resource helpers, not numeric logical lines: line numbers follow resource-name order. The Feather map includes red LED, user button, NeoPixel data and NeoPixel power; see [configuration](CONFIGURATION.md).

## Build and package

On a host, a service is a freestanding shared library wrapped by `micros_tooling/storage/native_image.py` into `.mimg`. CMake's examples show the required flags and dependencies. Linux uses the restricted ELF64 profile; macOS ARM64 uses restricted Mach-O. On ESP32:

```sh
python micros_tooling/platforms/esp32/build_service.py \
  --firmware build/esp32-runtime/micros_runtime.elf \
  --output build/my-service --slot 3 --source path/to/service.c
```

The source exports the default descriptor symbol `micros_descriptor`; use `--descriptor-symbol` for another name. Multiple `--source` and `--define` arguments are supported. `.cpp`, `.cc` and `.cxx` use the freestanding C++17 subset. No exceptions, RTTI, TLS, dynamic constructors, hosted-library imports or unresolved relocations are supported. C++ state uses placement construction and explicit destruction in the arena.

ESP32 executable and writable slot capacities come from the selected base profile.
The current flash-service profile executes code and constants through flash
mappings; legacy profiles use RAM. Check the base's exported capacities rather
than applying historical slot sizes to every build. The builder rejects overflow,
unsupported sections/imports, and relocations. It links to fixed slot addresses
exported by the base; a mismatched base or a duplicate slot in a graph is rejected.
See the [flash-service profile](architecture/flash-services.md) for its layout
and the scope of its measurements.

Build a `.msp` with `microsctl package MANIFEST IMAGE OUTPUT --schema NAME=PATH`. Use the generated demo manifests as the exact format example. The manifest must match the native descriptor's memory requirements. Package identity includes image SHA-256 and canonical schema digests; installed name/version pairs are immutable. Change the version for source or contract changes. The application builder records a separate source build identity so placement and board-binding changes can relink an unchanged version; legacy packages without it use exact-image checks. See [operations](OPERATIONS.md). Persistent-data version must remain zero: no service-data migration API is implemented.

Install locally and use `plan` before activation, or deploy all desired board packages with `micros_remote.py --host DEVICE_IP deploy PACKAGE...`. Graph admission includes every service, channel, handle, arena and platform stack. Remote deployment stops the graph during staging, protects its known-good bank and confirms a candidate only after bounded liveness. See [the deployment/retry contract](../../../src/firmware/management/README.md).

## Analog inputs (ABI 0 revision 6)

`args->api->gpio_read_analog(context, owned_gpio, &raw)` reads a raw 12-bit ADC value. It uses the existing exclusive GPIO grant and handle, and `gpio_close` releases it. ESP32 supports input GPIOs on ADC1 with 12 dB attenuation; ADC2 is unavailable to this API. The value is unchanged on errors, and unsupported platforms return `MICROS_ERROR_UNSUPPORTED`. Digital reads of an input configured for ADC are unsupported until it is closed. See [pin-monitor](../../../src/services/pin-monitor/README.md) for a bounded sampling service.

## Device-independent coordination

ABI 7 supports generated typed state/action/event ports. Use the generated `SERVICE` macro and named callbacks to let the adapter own coordination handles, action tracking, and dispatch. See [coordination callbacks](COORDINATION.md#generated-service-callbacks) for the application interface and its loss, concurrency, and restart contracts. Low-level operations remain available.
