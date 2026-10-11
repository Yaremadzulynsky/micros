# Resources

> Historical architecture discussion and milestone resolutions. The [V1 architecture](../../v1-architecture.md) and [implemented feature matrix](../V1.md) take precedence over original proposals below.

Status: Working architecture. Original direction and review proposals are preserved below. The M0 contract, where present, takes precedence for the initial implementation; other proposals remain unaccepted.

## 6. Memory Model

micros does not assume MMU-style process isolation on targets that cannot provide it.

### Deterministic allocation

The intended model is:

- Persistent state lives in flash/filesystem storage.
- Runtime state lives in RAM.
- Each loaded service receives a defined RAM budget/region.
- Runtime memory requirements are declared before execution.
- Prefer static allocation or allocation during initialization.
- Avoid unrestricted runtime heap growth.

At boot, micros reads the installed/enabled service manifests and lays out service memory from a clean state.

```text
RAM
┌────────────────────┐
│ Kernel             │
├────────────────────┤
│ Service A          │
├────────────────────┤
│ Service B          │
├────────────────────┤
│ Service C          │
├────────────────────┤
│ IPC buffers        │
└────────────────────┘
```

When services are installed/removed and the layout becomes inconvenient, **reboot and deterministic relayout is an acceptable design mechanism**. micros does not need to reproduce Linux virtual-memory behavior.

### Isolation limitation

A memory budget controls how much memory micros gives a service. Without suitable hardware protection, it does **not** prevent buggy native code from writing outside that region.

**Current limitation (explicitly recorded 2026-09-08): service memory boundaries are not enforced against native reads or writes.** Admission checks enforce declared budgets, but services must respect arena and stack boundaries by convention. A faulty service can corrupt another service, the kernel, or resident management and crash or reboot the whole device. Resident management is not memory-isolated from services.

Disallowing dynamic allocation does not establish isolation: fixed arrays, stack use, and arbitrary pointers can still corrupt memory. An arena-backed allocator can enforce its own allocation limit for cooperative callers, but cannot contain arbitrary native code. Enforced containment requires a hardware-protected execution model or sandboxed execution; neither is provided by the current native-service contract.

Therefore micros should additionally favor:

- No shared service pointers.
- Message passing.
- Stack canaries/guard mechanisms where possible.
- Strong validation/assertions.
- Safer implementation languages where appropriate.

Hard memory isolation may be added on targets that provide suitable MPU/MMU capabilities.

### Allocation conventions and telemetry follow-up

Discussion recorded 2026-09-08; the rules below are proposed follow-up work, not implemented guarantees.

Inspection of the button, colors, logger, and DHT application services found a fixed-state pattern: each declares `arena_bytes = sizeof(state_type)` and accesses that state through a typed pointer to `args->arena`. These services do not need a general dynamic allocator for their current persistent state. Adding fields to the state struct increases its declared reservation automatically. Stack-local buffers and image data are separate from the arena reservation.

Raw pointers are still used for state access, callbacks, message buffers, and hardware-register access in the DHT and NeoPixel drivers. The resident management implementation also uses `malloc`/`calloc` for request and response storage; its allocation behavior is separate from the application-service state pattern.

Proposed conventions:

1. Prefer fixed state structs with arena reservations derived from `sizeof`, rather than manually maintained byte counts.
2. When variable workspace is necessary, provide one standard bounded arena allocator with explicit allocation failure, current usage, peak usage, and failure counters. Define whether reported usage includes allocator metadata and alignment overhead.
3. Require buffer-writing helpers to accept destination capacities, particularly formatting and copy helpers. The DHT service's `append` and `number` helpers currently advance output pointers without a capacity argument; this is a review target, not evidence of an observed overflow.
4. Check unsupported allocator dependencies during packaging. This constrains supported allocation paths, not arbitrary native memory access.

The console currently reports service reservations; private arena usage is unmeasured, as documented in the [heap-accounting review](../reviews/heap-accounting-console-validation.md). A service writing 25 bytes into a 10-byte region does not create a tracked 25-byte allocation: it corrupts adjacent memory and need not change the reported reservation. A correctly bounded allocator would reject a request exceeding its available capacity instead. Future allocator telemetry must not be presented as detection of all memory writes or as memory isolation.

Standardizing allocation is a comparatively contained improvement to predictability and diagnostics. It does not contain out-of-bounds accesses, stack overflow, or arbitrary pointer writes; the isolation limitation above remains applicable.

---

## 7. Hardware Model

micros exposes **generic hardware primitives**, not APIs for individual devices.

Examples:

```text
GPIO
UART
SPI
I2C
timers
network
storage
```

A temperature sensor driver, IMU driver, motor driver, etc. is implemented as a service using those primitives.

This means adding a new peripheral should normally require deploying a new service, **not rebuilding micros**.

Resource APIs should preferably return opaque handles rather than exposing ownership internals directly. micros can then track resource ownership and detect conflicts.

For timing-critical operations, the native implementation performs the tight hardware operation rather than forcing repeated high-overhead cross-boundary calls.

---

### 19.4 Trust Model and Remote Management

**Established direction:** memory budgets do not establish isolation on unprotected targets; v1 remote updates apply only to services.

**Open:** package authorization, management authentication, and platform enforcement.

**Proposal:** define v1 services as trusted native code. Require authenticated remote management and authorized packages before activation. Choose the credentials, signature policy, and provisioning workflow separately.

Excluding kernel writes from remote APIs is an API restriction. Without effective hardware privilege separation, it is not a guarantee against arbitrary native code accessing the underlying platform. Any stronger guarantee must name the enforcing hardware and software boundary.

Capabilities should distinguish resource admission and ownership checks from protection against malicious native code. A request for `spi` alone does not define which controller, pins, device, or sharing mode is authorized.

### 19.5 Complete Resource Accounting

**Open:** the exact meaning of every declared resource budget.

Admission must account for executable memory, data/BSS, stacks, service arenas, IPC storage, subscriber state, serialization buffers, timers, handles, and required hardware resources. Memory classes such as executable or DMA-capable memory must be checked separately where the target distinguishes them.

**Proposal:** allocate fixed-size message slots per channel for v1. A channel's storage is its depth multiplied by its maximum payload size, plus slot and channel metadata. This favors predictable admission and simple overwrite handling at the cost of unused capacity for short messages.

The manifest must specify whether `runtime_bytes` includes or excludes stacks, code, and kernel-owned resources. Shared platform costs and transient installation costs must also fit the device budget.


## M0 Ownership and Admission Contract

Selected baseline for the initial implementation:

- Admission separates executable bytes, data/BSS, arena bytes, task stack, kernel task metadata, handles, and IPC buffers. `runtime_bytes` in the old manifest example is not normative. Stack and image sections are excluded from the ABI's `arena_bytes`.
- The kernel owns service allocations. Services own the contents of their arena and receive handles for admitted platform resources. SDK handle validation includes owner and generation. No v1 service-visible unrestricted allocator is provided.
- Stack size in the ABI is bytes. The BSP must translate to the underlying API's units and account for alignment/minimums. Host OS stack rounding is reported separately. Shared ESP-IDF and transient loader costs count in the target budget.
- M1 uses internal executable memory and internal data/stack allocations as supported by its loader proof; PSRAM is excluded from the initial admission budget until probed and tested.
- Stop prevents new work, then cancels or drains operations, detaches callback sources, joins the task, and only then reclaims service memory. No callback may target reclaimed service code. Failed cleanup requires reboot and keeps ownership intact until then.
- Partial init cleanup must release exactly the resources acquired so far. Kernel ownership tracking is authoritative even if service cleanup returns an error.

Exact pool sizes, hardware capabilities, handle encoding, and channel admission are M2–M4 decisions. These are ownership/accounting rules, not isolation against arbitrary native writes.

## M2 Ownership Implementation

The host manager now enforces bounded arenas/stacks, four service slots, eight handles per service, and four simulated exclusive GPIO lines. Timer and GPIO handles validate owner, generation, and resource type; exhausted generations retire. Kernel cleanup releases remaining handles after failed initialization or failed cooperative stop. A timed-out hook retains ownership for process recovery. See [M2 accounting and tests](../milestones/M2.md); IPC admission remains M3/M4 work.
