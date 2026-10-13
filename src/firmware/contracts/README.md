# Adding a platform

Every platform implements the same six APIs and declares its capabilities. There
is one shared controller, runtime and deployment format; no controller profile to choose.

| Shared contract | Platform implementation | Responsibility |
| --- | --- | --- |
| [platform.h](include/micros/platform.h) | `src/platform.c` or `.cpp` | Tasks, supervisor, synchronization, time, allocation, native loading, GPIO, reset and identity |
| [storage.h](include/micros/storage.h) | `src/storage.c` or `.cpp` | Logical image sets, graph records and durable activation selection |
| [transport.h](include/micros/transport.h) | `src/transport.c` or `.cpp` | Local console and authenticated requests, bounded replies and diagnostics |
| [network.h](include/micros/network.h) | `src/network.c` or `.cpp` | Connectivity, settings and network measurements |
| [update.h](include/micros/update.h) | `src/update.c` or `.cpp` | Base-image update and bootloader mechanisms |
| [telemetry.h](include/micros/telemetry.h) | `src/telemetry.c` or `.cpp` | Typed hardware measurements; shared code formats them |
| [capabilities.h](include/micros/capabilities.h) | `target_config.h` | Explicit support flags, target identity and controller resource budgets |
| [memory.h](include/micros/memory.h) | `src/platform.c` on static targets; inline heap backend elsewhere | Separate bounded application and management allocations |

```text
platforms/<name>/
  target_config.h
  src/
    platform.c       # C++ is allowed where the SDK requires it
    storage.c
    transport.c
    network.c
    update.c
    telemetry.c
    support/         # private SDK helpers, flash geometry and headers
  sdk/               # startup, SDK build files, linker scripts and boot integration
```

1. Create this layout and implement the declared operations. Keep SDK types and
   physical addresses inside the platform. An unavailable optional operation has
   an explicit unsupported implementation; it must not silently report success.
2. In `target_config.h`, declare every capability and the memory budgets. Builds
   requiring a disabled capability fail compilation through
   `MICROS_REQUIRE_CAPABILITY(NAME)` or `MICROS_REQUIRE_<NAME>` build flags.
   Missing backend operations fail linking. Dynamic requests still need runtime checks.
3. Have SDK startup call `micros_controller_run()`. Compile the shared `controller/`
   and `kernel/` with this platform, selecting its root for `target_config.h`.
   Follow an existing SDK source list for the chosen toolchain.
4. Run `build/python/bin/python tests/platforms/contract_test.py`. The
   [SDK-free fixture](../../../tests/platforms/fake/) demonstrates the complete
   surface and links the real shared controller. It references every declared
   operation and checks missing operations and unsupported build requirements.
   Its scheduler and loader are test doubles, not a functioning port.
5. Add the target's native image/board definitions and SDK tooling. Register its
   name, native IDs, default board and CLI provider in
   [`platforms/registry.py`](../../micros_tooling/platforms/registry.py).
   The registry controls dispatch, discovery identity and starter choices; the
   provider supplies the target's build, enrollment and flash mechanisms.
6. Build the target, verify stack/RAM limits, then test its scheduler, storage
   interruption recovery and transport on hardware. A link check cannot establish these.

The framework's own headers are separate: `controller/include/micros/` contains
application lifecycle, controller commands, the deployment record and reporting;
`kernel/` contains runtime and loader internals. A port uses these shared types and
implementations rather than reimplementing them. Application services use the
ABI in `src/sdk/abi/include/micros/`.

## Management and application memory

The shared RPC parser reserves one bounded reply workspace before applications
start. A transport borrows it until its final read and must release it with
`micros_controller_rpc_release`; it must never free the pointer. The controller
serializes reply creation. USB receives an explicit pre-execution busy response
while the relay owns that workspace. Poll telemetry releases its storage once
sent; mutation replies remain available until acknowledged. This keeps status
and recovery replies independent of application heap availability.

SAMD21 and ESP8266 reserve the runtime, task control blocks, semaphores and
supervisor stack statically. Service stacks, arenas, immutable configuration,
channel payloads and coordination records use a fixed application pool. Stacks
are reserved during admission, before any service hook runs. Ordinary channels
do not reserve coordination records. Blocks are aligned to 16 bytes, include a
16-byte header and coalesce on release. Exhaustion returns a capacity error;
there is no heap fallback. Host and ESP32 keep their existing allocation backend.

Management staging uses a separate fixed pool on these small targets, so application
admission cannot consume the memory needed to stop or replace an application.
The controller validates aggregate application costs before stopping a running
graph. The CLI also charges coordination records from package declarations.
The seven platform operation contracts are supplemented by `memory.h`, which
selects the allocation backend. Networking-library allocations remain separate;
SAMD21's linker reserves at least 1 KiB for those and 2 KiB for the interrupt stack.
Hardware measurements must establish that these allowances cover actual peaks.

Target startup selects a controller-task stack separately from the total service
stack budget. SAMD21 and ESP8266 expose its measured unused margin as
`heap_accounting.controller_stack_free`, alongside reserved management reply
bytes. Validate peak usage during activation and network connection establishment,
not only idle heap. TLS work and platform networking buffers are additional costs.

Embedded status identifies its layout version and each service's physical slot.
The host expands this compact geometry into the flash inventory without allocating
partition JSON on the controller. CLI deployments publish service/channel labels
bound to the exact base and graph hashes, including USB deployments when an
operator server is configured. Missing stored-image measurements remain unknown;
partition reservations are never reported as measured free space.
