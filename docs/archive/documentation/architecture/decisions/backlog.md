# Decision Backlog


This is the original pre-implementation backlog, preserved for traceability. D-001 through D-010 were addressed within the M0–M8 prototype scope; the open wording in the table records the questions at that time, not current blockers. See the [decision index](README.md), [current architecture](../../../../site/architecture.md) and [current review findings](../../reviews/documentation-design-review.md) for present status.

| ID | Decision | Required outcome |
| --- | --- | --- |
| D-001 | First MCU target and platform substrate — partially resolved | ESP32-PICO-V3-02 selected and verified; carrier board, BSP dependencies, and scheduler ownership remain open |
| D-002 | Service execution model | Execution contexts, blocking rules, priority, and watchdog contract |
| D-003 | Lifecycle and teardown | State transitions, ownership, shutdown deadlines, and failure recovery |
| D-004 | Target ABI and native loader | Working MCU feasibility prototype and supported toolchain constraints |
| D-005 | Resource admission | Complete accounting and rules for each bounded resource/memory class |
| D-006 | Local IPC | Slot layout, synchronization, cursor semantics, and operation results |
| D-007 | Package and interface metadata | Manifest encoding, schema identity, compatibility, and dependencies |
| D-008 | Installation and activation | Power-loss-safe commit, health criteria, and rollback behavior |
| D-009 | Management trust boundary | Authentication, package authorization, and enforcement limitations |
| D-010 | Recovery/base image | Boot selection, partition capacity, and physical recovery workflow |

A resolved decision should record its status, rationale, alternatives considered, consequences, and validation evidence. The relevant architecture section should then be updated so the decision log does not become a competing specification.

