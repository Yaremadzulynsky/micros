---
title: Service API
hide:
  - toc
---

<span class="docs-editorial"></span>

Reference · Service API
{: .arch-eyebrow}

# Service API

The native ABI connects separately compiled services to the kernel. The kernel's
[platform contract](../../src/firmware/contracts/include/micros/platform.h) supplies target
facilities below that boundary. One shared kernel codebase does not mean one
binary runs on every controller.
{: .arch-intro}

<figure class="arch-flow"><div><strong>Service</strong><span>Public API table</span></div><b aria-hidden="true">→</b><div><strong>Kernel</strong><span>Lifecycle & ownership</span></div><b aria-hidden="true">→</b><div><strong>Platform</strong><span>Tasks, time & hardware</span></div><figcaption>For example, a service's monotonic_us call reaches the platform clock through the kernel.</figcaption></figure>

## 01 · Lifecycle {#lifecycle}

The [public C header](../../src/sdk/abi/include/micros/service.h) defines exact ABI
identity, signatures, and error codes. Services require the matching revision,
target calling convention, and base layout. Use generated hooks for new services;
the manual descriptor exposes these native entry points:

| Hook | Contract |
| --- | --- |
| `init` | Initialize state and decode settings; cleanup must tolerate partial success. |
| `start` | Begin work after initialization. |
| `step` | Perform bounded work and return. |
| `stop` | Release resources; opening new resources is rejected here. |
| Timer callback | Runs serially with hooks on that service's worker. |

`MICROS_OK` means success; a nonzero hook/callback result fails the service and
enters cooperative cleanup. Generated lifecycle ownership is described in
[Write a service](write-a-service.md); manual ownership is illustrated by
[hello](../../examples/hello-service/src/service.c).

## 02 · State and timers {#state-and-timers}

The runtime supplies an aligned, zeroed arena, read-only API table, opaque context,
and immutable configuration valid through stop. Retain instance state in the arena;
pass the context unchanged to API calls. Never inspect or free the context.

Manual timer creation uses microseconds:

```c
args->api->timer_open(args->context, 1000000, 1000000,
                      print_hello, NULL, &state->timer);
```

The first duration is delay and the second period. Zero period means one-shot;
its handle still needs closing. Late periodic deliveries coalesce. Closing a timer
prevents later dispatch for that handle; callback data must remain valid until
closure or completed stop. Generated named-timer helpers use the same semantics.

C services use C17. Freestanding C++17 avoids exceptions, RTTI, thread-local storage,
dynamic static initialization, and host-library imports. See the
[C++ example](../../examples/cpp-service/src/service.cpp).

## 03 · Resources {#resources}

| Budget | Holds |
| --- | --- |
| Native image | Executable code and constants |
| Writable reservation | Initialized data and BSS |
| Instance arena | State between hooks |
| Worker stack | Call frames and temporary data |
| Shared storage | Channels and runtime bookkeeping |
| Handles/grants | Timers, ports, and permitted hardware |

Admission checks these independently against the selected target/base. PSRAM is
available only on supporting profiles; code in flash does not remove RAM needs.
See [format ceilings](declaration-authoring.md#limits-and-validation).

Current MKR and ESP8266 bases reserve separate fixed application and management
pools. Service stacks, arenas, configuration and channel payloads use the bounded
application pool; pool exhaustion returns a capacity error, with no fallback to
the library heap. Wi-Fi/TLS libraries still allocate from their own heap. Host and
ESP32 retain their existing heap-backed implementation. Available heap therefore
does not measure unused service-pool capacity on every target.

On ESP8266, background `step` work is scheduled at a 10 ms interval so services
leave CPU time for networking. Timer deadlines are scheduled independently;
callback timing still depends on scheduling and bounded hook execution.

Managed handles are owner checked and generation tagged; zero is invalid.
`CAPACITY` means no bounded resource could be granted; `UNSUPPORTED` means the
operation is unavailable; `STALE_HANDLE` rejects an old/foreign identity.
Generated typed bindings own message encoding—do not use the private `_ipc` table.
[Connect services](connect-service-ports.md#choose-retention) defines read/loss results.

## 04 · Failure and memory boundaries {#failure-and-memory-boundaries}

| Failure | Boundary |
| --- | --- |
| Hook returns an error | Cooperative cleanup can release its resources. |
| Hook/callback does not return | Supervisor detects overdue work; runtime/device recovery may be necessary. |
| Native code writes invalid memory | Peers, kernel, or management can be corrupted. |

Services share an address space. Ownership checks are not memory isolation, and
deadline detection is not a hard real-time guarantee. Code, arena, and stack memory
cannot be reclaimed while an executing worker could still reference them. Hardware
output states during stop/reboot remain application and electrical design choices.
