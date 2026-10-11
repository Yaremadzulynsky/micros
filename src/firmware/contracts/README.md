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
