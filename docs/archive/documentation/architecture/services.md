# Services

> Historical architecture discussion and milestone resolutions. The [V1 architecture](../../v1-architecture.md) and [implemented feature matrix](../V1.md) take precedence over original proposals below.

Status: Working architecture. Original direction and review proposals are preserved below. The M0 contract, where present, takes precedence for the initial implementation; other proposals remain unaccepted.

## 3. Services Are the Unit of Deployment

A service is the smallest independently installable, replaceable, startable, and stoppable unit in micros.

An installed service consists conceptually of:

```text
service package
├── manifest
└── native executable image
```

Services are stored persistently in flash. Installing a service does not imply that it must be resident in RAM.

For example, a device might have 16 installed services but only load four for the current configuration.

### Native, Language-Agnostic Target

The current design direction is **native services without a mandatory WASM or language runtime**.

micros defines a stable ABI. Any language/toolchain capable of producing a compatible native service can target micros:

```text
C ------C++ -----Rust ------> micros native service ABI
Zig ------/
AOT lang -/
```

Dynamic languages may only participate if an external toolchain can ahead-of-time compile them to the micros native target. micros itself does not need to embed a Python/WASM/etc. runtime.

---

## 4. Uniform Service Interface

**Every service implements the standard micros service interface.**

The kernel must not need service-specific knowledge to manage a service.

The exact ABI is still to be finalized, but conceptually:

```c
service_init(...);
service_start(...);
service_stop(...);
```

Additional lifecycle/event hooks may include mechanisms such as message or timer handling, but those signatures remain an open design item.

A service descriptor provides metadata/entry information needed by the loader. Conceptually:

```c
struct ServiceDescriptor {
    /* ABI/version information */
    /* lifecycle entry points */
    /* other loader metadata */
};
```

The precise binary representation is TBD.

---

## 5. Service Binary / Loader Model

micros needs a loader capable of taking an independently compiled service and making it executable.

A full ELF loader is **not required by the architecture**. A purpose-built executable format may be preferable.

A minimal service image could begin with a fixed binary header containing fields such as:

```text
magic
format_version
ABI_version
entry_offset / descriptor_offset
code/data sizes
required runtime memory
flags
```

The loader can then:

1. Validate the image and ABI.
2. Allocate the service's runtime memory.
3. Load/copy executable material as required by the chosen format.
4. Locate the service descriptor/entry point.
5. Bind the service to the micros API.
6. Initialize and start it.

The exact executable format, relocation strategy, and whether executable code runs from RAM or flash remain open questions.

### Important Flash Constraint

A general filesystem such as LittleFS may scatter a file across flash blocks. Therefore, storing a service as a normal filesystem file does **not automatically mean it can execute directly from that location**.

One candidate model is:

```text
Flash / filesystem
    ↓ load
Service RAM region
    ↓
Native execution
```

This works naturally with the idea that only a subset of installed services are loaded at once.

---

### 19.1 Execution and Scheduling

**Open:** what executes a service and what scheduling guarantees micros provides.

The lifecycle ABI cannot be finalized until the execution context is defined. The contract must specify:

- Whether each service has a task/thread or shares an event loop.
- Whether lifecycle hooks and message handlers may block.
- Whether services can create additional execution contexts.
- Priority assignment, interrupt interaction, and CPU starvation behavior.
- Shutdown deadlines and watchdog behavior.
- Which scheduling mechanisms come from the BSP or an underlying RTOS.

**Proposal:** start with one preemptively scheduled task per running service, backed by the platform scheduler, with declared priority and stack size. Additional service-created tasks would require an explicit resource contract.

Deterministic memory allocation does not by itself guarantee bounded execution latency or deadlines. Timing guarantees remain open.

### 19.2 Native ABI and Loader Feasibility

**Established direction:** independently compiled native services use a stable, language-agnostic interface.

**Open:** the supported target ABI profiles, executable representation, relocations, and SDK import mechanism.

A target ABI profile must identify the instruction set, calling convention, endianness, alignment, and relevant compiler/runtime constraints. Source portability is distinct from native binary portability. A service image must identify its target as well as its micros ABI version.

The ABI must eventually specify:

- Fixed-width public types, structure layout, version negotiation, and error representation.
- Ownership and lifetime of buffers passed across the boundary.
- SDK binding and unsupported-import behavior.
- Initialization of data and BSS, constructors, and runtime dependencies.
- Rules for exceptions, unwinding, thread-local storage, and language runtime support.
- Validation of image lengths, offsets, alignment, relocation ranges, and arithmetic overflow before execution.

**Proposal:** prove a minimal independent service loader on the first MCU before selecting the final package or executable format. The prototype must exercise SDK calls, mutable globals, stop/reload behavior, and incompatible-image rejection. A desktop-only prototype is insufficient evidence for MCU executable-memory feasibility.

### 19.3 Lifecycle, Ownership, and Teardown

**Open:** lifecycle state transitions and failure semantics.

A lifecycle specification must distinguish installed, loaded, initialized, starting, running, stopping, stopped, and failed states, or explicitly justify a smaller state model. It must define which operations are legal in each state and whether they are idempotent.

**Proposal:** stopping a service proceeds through these steps:

1. Request cooperative shutdown and prevent new service work.
2. Quiesce or cancel outstanding operations, including DMA and bus transactions.
3. Detach interrupt callbacks, timers, and other asynchronous entry points.
4. Release owned handles and subscriptions.
5. Reclaim executable and runtime memory only after no execution can reference it.

The ordering must be refined per resource type. Reclaiming memory is unsafe while code, callbacks, or hardware operations can still reference it.

**Proposal:** if teardown cannot complete safely within its deadline, use a controlled device reboot rather than forced reclamation. Restart after an arbitrary native fault is not assumed to restore shared-memory integrity.


## M0 Execution Contract

Selected baseline; supersedes the scheduling and lifecycle proposals above for M1.

- Each loaded service instance receives one managed task. ESP-IDF FreeRTOS supplies MCU scheduling; the host uses a POSIX thread per instance. The kernel never implements its own scheduler in v1.
- All lifecycle hooks execute serially on that instance's task: `init`, `start`, repeated `step`, then `stop`. No two hooks overlap. Services cannot create threads, install ISRs, or invoke platform APIs directly through the supported SDK.
- `init` establishes service state in the provided zeroed arena; `start` begins operation. `step` performs one bounded unit of work and returns. For M1 the runtime yields with a 1 ms nominal delay between steps; event-driven waits belong to M2/M3.
- Hooks must not wait indefinitely. Initial harness deadlines: 1 second each for init/start/stop and 10 ms for a step. These are failure-detection thresholds, not guaranteed scheduling latency. Measure and revise them during M1.
- Stop is a supervisor-owned request checked between hooks; it never invokes stop concurrently with a running hook. SDK waits introduced later must be cancellable.
- The ESP32 baseline pins service tasks to core 1, priority 5; the supervisor uses priority 6 on core 1. These values are deployment policy, not ABI fields. Initial services cannot choose arbitrary priority or affinity. BSP/system tasks retain ESP-IDF scheduling. Host priority/affinity is best effort and does not emulate MCU timing.
- A stalled hook leaves its allocations resident. The supervisor reports a failure and requests device reboot; it does not free memory underneath execution or forcibly cancel a host thread. The host harness exits its process on this failure.
- The MCU platform will enable interrupt/task watchdog coverage and a 5-second initial watchdog timeout with panic/reboot behavior. Exact SDK configuration is verified in M1. Native faults require whole-runtime recovery because shared state may be corrupt. Watchdogs are not a security boundary against trusted native code.

### Lifecycle State Machine

Installation is persistent metadata, independent of execution state.

| State/trigger | Next state | Required action |
| --- | --- | --- |
| Unloaded + load | Loaded | Validate image and reserve all resources; no service code executes |
| Loaded + launch | Initializing | Create task; invoke init with zeroed arena |
| Successful init | Starting | Invoke start |
| Successful start | Running | Invoke bounded steps until stop/error |
| Running + stop | Stopping | Suppress new steps; invoke stop after current step returns |
| Hook returns an error | Stopping | Record error; run stop if init was entered, including partial init failure |
| Stop returns and platform is quiescent | Stopped or Failed | Join task; successful requested stop is Stopped, hook failure is Failed |
| Stopped/Failed + unload | Unloaded | Reclaim only after all callbacks/operations are detached |
| Any hook times out or native fault | Failed, reboot required | Keep allocations; recover whole runtime |

A pending stop during init/start skips remaining forward hooks once the current hook returns and enters cleanup. `stop` must tolerate partially initialized state. Stop on Stopped/Unloaded is an idempotent success; starting a Running instance is an invalid-state error. Restart means safe unload, fresh data/BSS and arena initialization, then launch. There is one instance per loaded image in M1; multiple independent instances are deferred.

### Minimal ABI Profile

The authoritative declarations are [service.h](../../../../src/sdk/abi/include/micros/service.h). This is experimental ABI 0, revision 1; exact revision matching is required. Any layout or semantic change increments the revision before interoperability testing. There is no stable ABI promise until M1 evidence is reviewed.

- MCU profile: 32-bit little-endian Xtensa ESP32 using the selected ESP-IDF compiler's windowed C calling convention. M1 must verify compiler flags and emitted relocations. Host profile: native macOS arm64 C ABI, 64-bit pointers. Profiles are deliberately binary-incompatible.
- Public numbers use fixed-width integers; no enums, bitfields, packed structures, variadic calls, C++ classes, or platform types cross the boundary. Structures use native target alignment. Pointer-containing structures are in-memory interfaces, never serialized package headers.
- The descriptor identifies target, ABI revision, required arena size/alignment, stack bytes, and four required hooks. Reserved fields must be zero. Layout size must match for this experimental revision.
- The loader supplies a constant API table, opaque instance context, and zeroed arena. They remain valid through stop completion. Services may retain these within their own state but never share them with another service.
- The M1 API only exposes a bounded synchronous diagnostic write and monotonic time query. Diagnostic output is a kernel debug facility; inter-service logs must use protobuf IPC when that exists. Writes accept at most 256 bytes, copy/use data before return, may return a capacity error, and never retain the caller's pointer.
- No runtime heap allocation, TLS, constructors/destructors, exceptions, unwinding, or hidden runtime imports are supported by M1 services. Compiler-generated helpers must be either linked into the image within its budget or rejected. A freestanding C service is the first producer.
- The descriptor is discovered using an exported query function on the host; the MCU representation is decided in M1. Validate an outer image envelope before loading executable code. In-memory descriptor checks alone do not validate a disk image or make host dynamic loading safe for untrusted code.

### M1 Loader Experiment Boundary

Use host dynamic loading for iteration; investigate a restricted ELF-derived MCU image and inspect real Xtensa relocations before implementing a format. Neither ELF nor a custom executable format is selected by M0. Record code/data placement, executable allocation, cache synchronization, imported symbols, and malformed-image rejection in M1. Do not assume ordinary RAM or PSRAM can hold executable code.

## M1 Implementation Resolution

The [native image profile](native-image.md) and [ADR 0004](decisions/0004-m1-fixed-slot-loader.md) resolve executable representation and MCU descriptor discovery for the experiment. The MCU reads the descriptor directly from validated initialized data. The initial loader has one fixed slot and no runtime relocations; multi-service placement remains open for later work. These decisions supersede the earlier M1 format/discovery questions, without claiming a general deployment loader.

## M2 Runtime Resolution

[ADR 0005](decisions/0005-host-runtime-ownership.md) and the [M2 record](../milestones/M2.md) define the implemented host manager. The current experimental ABI is 0 revision 2, with timer and simulated-GPIO callbacks appended to the API table. Exact revision matching remains required; earlier M0/M1 revision-1 notes are historical.

Lifecycle and timer callbacks are serialized on one managed worker, with independent deadline supervision. Stop suppresses new dispatch/acquisition, drains active work, invokes partial-init-safe cleanup, releases owned handles, and joins before unload. A stale service identity is rejected; stop idempotence applies to an extant Loaded/Stopped instance, not an identity already invalidated by unload. Restart requires a fresh load. See the M2 record for resource and timeout policy.

## M3 API Resolution

The current API is experimental ABI 0 revision 6, adding raw ADC reads through owned GPIO handles. Startup configuration remains immutable and IPC dispatch stays behind generated service interfaces. See [configuration](../CONFIGURATION.md). Earlier revision-1/2 notes record milestone history. Host work deadlines are now 100 ms after multi-service scheduling measurements; the MCU M1 proof keeps its separate 10 ms step policy. See [M3](../milestones/M3.md).
