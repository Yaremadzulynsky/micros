> Historical architecture snapshot retained during the repository reorganization.
> Some scope statements are superseded; use the [current architecture](../site/architecture.md).

# micros V1 architecture

micros runs independently compiled, trusted native services on an ESP32 Feather V2 and desktop hosts. A shared C17 kernel manages serialized lifecycle hooks, bounded memory/resources, protobuf channels and transactional service activation. POSIX threads implement host execution; ESP-IDF FreeRTOS tasks and the board BSP implement device execution. The service ABI remains experimental **major 0, revision 7**, with exact revision matching.

## Implemented contract

| Area | V1 behavior | Authoritative detail |
| --- | --- | --- |
| Native loading | Restricted Mach-O on macOS ARM64; restricted ELF64 on Linux ARM64/x86-64; four independent fixed IRAM/DRAM slots on ESP32 | [Native image profile](documentation/architecture/native-image.md) |
| Lifecycle | One worker per service; serialized init/start/step/stop and timer callbacks; ownership cleanup and join before reclaim; timeout requires runtime/device recovery | [M2 lifecycle contract](documentation/milestones/M2.md), [SDK guide](documentation/SDK.md) |
| Resources | Admitted arenas, platform stacks, generation-aware handles, timers and GPIO; whole-graph resource budgets | [M4 admission](documentation/milestones/M4.md), [V1 limits](documentation/V1.md) |
| IPC | Bounded stream/latest channels, independent subscriber cursors, copied protobuf bytes, explicit loss and capacity results | [M3 IPC contract](documentation/milestones/M3.md) |
| Hardware | Deployment-owned GPIO bindings; Feather button GPIO38 publishes debounced states and Colors drives GPIO0/2 through named grants | [Configuration](documentation/CONFIGURATION.md), [Colors driver](../../src/services/colors/README.md) |
| Packages | Immutable name/version packages, image/schema identities, explicit interface compatibility, separate installed/desired/running state | [Package contract](documentation/architecture/decisions/0007-service-packages.md) |
| Activation | Two bounded device banks, committed selection journal, two boot trials, five-second liveness confirmation, known-good fallback | [M6 recovery contract](documentation/milestones/M6.md) |
| Management | Privileged base-linked TLS service, physically provisioned credentials, bounded authenticated requests delegated to the same controller | [Management API and trust](../../src/firmware/management/README.md) |
| Languages | C17 and tested freestanding C++17 subset implement the same C ABI | [C++ example](../../examples/cpp-service/README.md) |

Application services are linked and deployed independently of the base. Replacing one does not require rebuilding or flashing the kernel. A base rebuild that moves fixed slot addresses requires relinking the service images against that base ELF. Remote deployment replaces an admitted graph with explicit staging downtime; the previous good graph remains recoverable.

Services are trusted native code. Arena accounting, API permissions and checked handles do not provide hardware memory isolation. The management token authorizes native-code installation; package digests establish integrity, not publisher signatures. The recovery controller and management service reside in the physically flashed base. There is no remote kernel/BSP/bootloader update or separate redundant recovery firmware image in V1.

## Service memory boundaries are not enforced

Resource admission enforces declared allocation budgets; it does **not** enforce where native service code can read or write. Services must respect their assigned arena and stack by convention. An out-of-bounds write, stack overflow, or invalid pointer can corrupt other services, the kernel, or management and can crash or reboot the entire device. Keeping management in the resident base does not isolate its memory from application services.

Banning dynamic allocation would not fix this: static buffers and pointers can also access memory outside their assigned region. Bounded allocators and checked APIs help cooperative code handle exhaustion, but are not a containment boundary. Current services must be trusted; enforced isolation would require a hardware-protected execution model or a sandboxed service runtime. See the [memory isolation limitation](documentation/architecture/resources.md#isolation-limitation).

## Scope and future work

The [historical V1 feature/resource report](documentation/V1.md) records M0–M8 scope and measurements, not current-base memory usage. Current configuration and graph format 3 are described in [configuration](documentation/CONFIGURATION.md); outbound management and the web console are described in [server operations](../../src/server/README.md). Event channels, distributed/network IPC, general peripheral drivers, arbitrary native relocations, memory isolation, service persistent-data migrations, signed-package distribution and kernel OTA remain future work. Five-second liveness does not establish application correctness, and reset fault injection is not analog brownout qualification.

The [topic archive](documentation/architecture/README.md) preserves original architecture proposals and decisions. Those proposals are historical design context; current configuration, SDK and operations guides take precedence over earlier milestone details. Later milestone contracts supersede earlier experimental limits where stated. This avoids treating an earlier proposal or M1-only harness constraint as a delivered feature.

All roadmap milestones M0–M8 are recorded in the [roadmap](documentation/ROADMAP.md). Start with [build/reproduction instructions](documentation/BUILDING.md) and the [service-author quickstart](documentation/SDK.md).

Experimental ABI 7 adds [device-independent coordination](documentation/COORDINATION.md): typed state/action/event ports backed by bounded runtime records and an optional authenticated server router. Volatile action ledgers are fenced on endpoint lifetime changes; durable physical exactly-once execution is not claimed.
