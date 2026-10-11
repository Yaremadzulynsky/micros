# micros Build Roadmap

> Status: M0–M8 complete; V1 validated
> Historical milestone record updated: 2026-09-05. Current source uses ABI 0 revision 6 and graph format 3; see [configuration](CONFIGURATION.md) and [server operations](../../../src/server/README.md) for subsequent work.
> Architecture: [micros architecture](../../site/architecture.md)

## Objective

Build a micros v1 that can install independently compiled native services, run a bounded service graph, exchange protobuf messages, and recover from unsuccessful service updates. Develop most behavior on a desktop host, while validating native loading on a real MCU early enough to influence the design.

M0–M8 are complete. The repository now contains architecture contracts, the experimental ABI, a host loader, an ESP32 loader harness, independent service builds, and host/hardware validation. See the [M0 record](milestones/M0.md) and [M1 evidence](milestones/M1.md). See the [M2 runtime record](milestones/M2.md). See the [M3 IPC record](milestones/M3.md). See the [M4 package/management record](milestones/M4.md). See the [M5 hardware record](milestones/M5.md). See the [M6 recovery record](milestones/M6.md). See the [M7 remote management record](milestones/M7.md). See the [M8 V1 release record](milestones/M8.md).

## Working Assumptions

- Use macOS as the initial developer host, matching the current workspace. Add Linux for automated host validation once the basic runtime works.
- The user-selected v1 target is the connected ESP32-PICO-V3-02 (revision v3.0), with 8 MB flash detected over serial. The carrier is Adafruit ESP32 Feather V2, with red LED GPIO13 and user button GPIO38; do not attempt simultaneous ESP32 and STM32 ports.
- Use ESP-IDF FreeRTOS tasks on the MCU and POSIX threads on the host, with serialized lifecycle hooks per service (ADR 0002).
- Use C17 and CMake/Ninja with experimental C ABI 0 revision 3. ESP-IDF v5.5.2 is selected for M1; M8 validates freestanding C++17 on the host and device.
- Use trusted native services in v1, with explicit limits on what software-only capabilities enforce.
- Permit reboot for activation, memory relayout, or unsafe shutdown.
- Keep remote kernel, BSP, bootloader, and recovery-image updates outside v1.

Host execution validates contracts and service behavior. It does not prove MCU executable-memory feasibility, hardware timing, privilege isolation, or power-loss safety.

## Milestone Summary

| Milestone | Outcome | Depends on |
| --- | --- | --- |
| M0 (complete) | Architecture contracts and initial target selected | — |
| M1 (complete) | Independently built service executes on host and MCU | M0 |
| M2 (complete) | Host runtime manages service lifecycle and bounded resources | M1 |
| M3 (complete) | Two services communicate through bounded protobuf IPC | M2 (complete) |
| M4 (complete) | Packages, admission, persistent configuration, and local CLI | M3 (complete) |
| M5 (complete) | The service graph runs on real hardware | M4 (complete) |
| M6 (complete) | Service activation and rollback survive interruption | M5 (complete) |
| M7 (complete) | Authenticated remote service management works | M6 (complete) |
| M8 (complete) | V1 release gates and reproducible demonstration pass | M7 (complete) |

M1 contains a deliberately small MCU experiment. M5 is the full BSP and hardware integration milestone. Avoid expanding the host runtime before resolving the MCU loading risk.

## Confirmed Target

The user selected the currently connected ESP32 on 2026-09-05. Identification using esptool.py v4.6.2 reported:

| Property | Observed value |
| --- | --- |
| Chip | ESP32-PICO-V3-02 |
| Revision | v3.0 |
| Features | Dual core, 240 MHz, Wi-Fi, Bluetooth, embedded flash and PSRAM |
| Crystal | 40 MHz |
| Detected flash capacity | 8 MB |
| Current macOS serial port | `/dev/cu.usbserial-564E0535011` |

The serial path is an observation, not a portable device identifier. PSRAM capacity and usable memory budgets have not been measured. M5 identifies the Feather V2 carrier and implements its onboard LED/button profile and development service partition layout. At M0, identification commands only loaded an esptool stub and reset the device. Later milestones physically flashed the base and tested persistent service updates.

M0 selected the SDK, language, execution model, and a serial-only board profile. M1 validated native execution; M5 established carrier identity and peripheral mapping; M6–M8 validated persistence, remote management and the final graph.

## M0 — Establish the Implementation Contracts

Status: Complete. See [evidence and scope](milestones/M0.md).

**Deliverables**

- Split the architecture into a short root overview and focused documents for services, resources, IPC, deployment, and decisions, preserving proposal status and avoiding duplicated contracts.
- Select the MCU, board, SDK version, host toolchain, implementation language, and build system.
- Resolve D-001 and D-002: platform substrate, execution context, blocking rules, priority ownership, and watchdog behavior.
- Draft the lifecycle state machine, resource ownership rules, and target ABI profile needed by M1.
- Define the first demo: a synthetic or hardware sensor publisher and a consuming logger, using one bounded protobuf channel.
- Establish a repository layout for kernel, public ABI/SDK, BSPs, tooling, examples, and tests.

**Done when**

A developer can identify exactly what will be built, what runs a service, what the first target supports, and which contracts remain provisional. Record decisions with rationale and consequences. Do not require every architecture question to be resolved before coding.

## M1 — Prove Independent Native Loading

Status: Complete with a fixed MCU slot and RAM-only transfer. See [evidence and limits](milestones/M1.md).

**Deliverables**

- A minimal host executable that loads a separately compiled service through a versioned descriptor and SDK API table.
- A minimal physically flashed MCU harness that loads a service built separately from its base image.
- A service exercising initialization, one SDK call, mutable globals/BSS, and cooperative stop/reload.
- A target profile covering calling convention, image sections, imports, supported relocations, executable memory, and compiler runtime restrictions.
- A decision on executable representation based on the experiment: a restricted existing format or a purpose-built image, with a documented conversion/build path.

**Done when**

- Changing and deploying the example service does not require relinking or reflashing the MCU base image. A development-only local transfer path is sufficient here.
- Both targets reject incompatible target/ABI images and malformed offsets before entering service code.
- Stop/reload reinitializes service state correctly.
- MCU measurements report code, data, stack, loader overhead, and executable-memory consumption separately where applicable.

**Decision gate**

If independent native loading cannot fit or work reliably on the chosen MCU, revisit target, relocation strategy, or execution placement before proceeding. A host dynamic library is acceptable for the host experiment but is not evidence that the MCU loader works. Record limitations instead of substituting statically linked services for this gate.

## M2 — Build the Host Service Runtime

Status: Complete. See [implementation and evidence](milestones/M2.md).

**Deliverables**

- Lifecycle manager implementing legal state transitions and explicit failures.
- Bounded per-service memory arenas, stacks, handle tables, and resource admission.
- Host BSP for execution, monotonic time, timers, and simulated hardware.
- Ownership tracking and generation-aware handles to reject stale resource references.
- Cooperative shutdown, callback quiescence, cleanup, and a defined timeout outcome.
- Diagnostic output for service state and resource usage.

**Done when**

Repeated start/stop cycles return tracked resources to baseline. Failed initialization unwinds resources, stale handles are rejected, and outstanding timer callbacks cannot enter reclaimed service code. An uncooperative service produces the documented timeout/reboot-required outcome without unsafe reclamation.

Host allocations and scheduling may use OS facilities, but service-visible resource limits must be enforced and separately accounted for.

## M3 — Implement Local Protobuf IPC

Status: Complete. See [contracts and validation](milestones/M3.md).

**Deliverables**

- Manifest-independent channel configuration fixtures to exercise the kernel before package tooling exists.
- Fixed-capacity `stream` and `latest` channels, bounded payloads, independent subscriber cursors, and channel generations.
- Publication synchronization and explicit results for empty reads, insufficient output capacity, oversized publication, and missed data.
- SDK encoding/decoding helpers with bounded storage and one example schema.
- Sensor-to-logger demo using independently built services.

**Done when**

Two subscribers advance independently; a slow subscriber receives an explicit loss result; wraparound does not expose torn messages; a stopped subscriber cannot stall publishing indefinitely; and recreated channels invalidate stale subscriptions. Malformed protobuf input is rejected by the receiving layer without exceeding its resource budget.

Use focused concurrency and boundary tests. Define what successful publication means without implying that a subscriber acted on the message. Defer `event` channels.

## M4 — Add Packages, Admission, and a Local CLI

Status: Complete. See [M4 evidence](milestones/M4.md).

**Deliverables**

- Versioned package and manifest formats that describe target ABI, memory, capabilities, channels, and interface dependencies.
- Tooling to build and inspect packages; schema identity and declared compatibility are separate concepts.
- A service store with separate installed and enabled/active selections.
- Admission planning for the entire enabled configuration, including kernel-owned channel costs and constrained memory classes.
- Local commands for install, list, start, stop, restart, and logs, with clear errors.
- Deterministic boot configuration loading; reject invalid configurations before starting the candidate graph.

**Done when**

More services can be installed than loaded. A configuration that exceeds a bounded resource is rejected with an actionable reason. Incompatible interfaces and target images are rejected. Reboot reconstructs the selected graph. The same packages and configuration produce the same admission plan on the same target profile.

Until M6, document that persistent activation is developmental and has no completed power-loss recovery guarantee.

## M5 — Integrate the Real MCU BSP

Status: Complete. See [M5 evidence](milestones/M5.md).

**Deliverables**

- Port lifecycle, resource admission, timers, storage access, and local IPC to the selected MCU substrate.
- Implement the generic peripheral primitives needed by the first demo, with ownership and cancellation behavior.
- Replace the synthetic sensor with a driver service using those primitives.
- Build the same service sources for host simulation and MCU execution.
- Document base-system, SDK, driver-stack, service, IPC, and transient memory costs.

**Done when**

The driver publishes readings to the logger on hardware; resource conflicts are rejected; stop/restart leaves no live callbacks or transactions referencing reclaimed state; and the complete graph fits measured target limits. Record latency and memory measurements under a defined load without claiming general hard-real-time guarantees.

## M6 — Make Activation and Recovery Transactional

Status: Complete. See [M6 evidence](milestones/M6.md).

**Deliverables**

- Staging, integrity validation, atomic active-configuration selection, and retention of the previous known-good configuration.
- Boot-attempt accounting, bounded health criteria, and fallback that does not depend on the failing candidate service.
- Capacity accounting for staged and retained packages.
- An explicit persistent-data compatibility policy; reject unsupported migrations or define their rollback behavior.
- A documented physical recovery workflow and decision on the minimal recovery/base image and partition layout.

**Done when**

Fault injection at each write/commit boundary yields either the prior valid configuration or a complete candidate configuration, never a partially selected graph. A crash loop falls back after the configured threshold. Demonstrate representative interrupted-update cases on hardware as well as simulated storage faults. Reverting code must not silently use incompatible persistent data.

## M7 — Add Remote Service Management

Status: Complete. See [implementation and hardware evidence](milestones/M7.md).

**Deliverables**

- A management service exposing service package transfer and lifecycle/diagnostic operations.
- Authentication, package authorization, credential provisioning, and bounded request processing.
- Reuse of the M4 admission and M6 activation paths for remote requests.
- Management APIs scoped to service-store operations, with no supported kernel/BSP/bootloader/recovery write operation.

**Done when**

A developer remotely installs and activates a service update, inspects its state/logs, and observes rollback after a failing candidate. Unauthorized requests fail before mutation; interrupted transfers do not change the active graph. Repeat requests have documented retry behavior.

The absence of a kernel-update endpoint is an API restriction, not proof of isolation against arbitrary trusted native code on an unprotected MCU.

## M8 — Validate and Document V1

Status: Complete. See [release evidence and scope](milestones/M8.md).

**Deliverables**

- Repeatable build and test commands for macOS, Linux, and the selected MCU.
- A second source-language service exercising the same ABI, to test the language-agnostic boundary.
- A scripted demonstration covering install, run, IPC loss, stop/restart, update, and rollback.
- A measured resource report, supported-feature matrix, and known limitations.
- SDK quickstart, service-author lifecycle/ownership guidance, package documentation, and physical recovery instructions.

**Done when**

A fresh checkout can reproduce the host demo and MCU artifacts with documented prerequisites. Automated host checks and the documented hardware validation suite pass. No unresolved blocker remains for native loading, teardown, admission, or interrupted activation. The root architecture describes the implemented v1 contract and clearly separates future proposals.

## Development and Validation Approach

For each milestone, implement the smallest end-to-end example, test its failure boundaries, record evidence, and update the relevant contract before expanding scope. Keep public interfaces provisional until their first host and MCU consumers exist.

Use host tests for state transitions, admission arithmetic, handle lifetime, IPC concurrency, parser rejection, and storage fault injection. Use hardware checks for executable placement, peripheral cancellation, target resource limits, and interrupted activation. Do not equate host success with hardware validation.

Do not attach calendar estimates yet: M1 can materially change the loader and target scope. After M1, estimate the remaining milestones using actual implementation throughput and observed constraints. Split a milestone into work items when it becomes the next active milestone.

## Deferred Scope

- Remote kernel/HAL/BSP/bootloader/recovery upgrades.
- Distributed IPC bridges, discovery, and routing.
- Reliable event delivery, durable messaging, and exactly-once effects.
- Multiple MCU families and a broad peripheral SDK.
- Strong service isolation beyond the selected hardware's demonstrated support.
- A general-purpose dynamic linker, unrestricted language runtimes, and unrestricted service-created threads/heaps.

## Immediate Next Work

Begin M5: port the bounded runtime and graph to the connected Adafruit ESP32 Feather V2. Use the user-authorized onboard red LED (GPIO13) and button (GPIO38) for the hardware service demo, verify placement/cleanup/resource costs, and preserve all host regressions.
