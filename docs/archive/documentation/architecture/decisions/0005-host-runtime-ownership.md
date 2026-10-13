# ADR 0005 — Serialized timers and generation-aware ownership

Status: Accepted for M2. Date: 2026-09-05.

M1 proved native loading but placed lifecycle logic directly in platform harnesses. M2 needs reusable state, resource accounting, and a teardown rule that cannot execute a timer callback after its image is unloaded.

Use a bounded manager with one worker per instance, a single management controller, and an independent deadline supervisor. Run lifecycle hooks and timers on the same worker. Timer deadlines participate in its condition wait; do not create one thread per timer. On stop, suppress dispatch and acquisitions before entering cleanup. Join before reclaiming an image.

Resource identities contain a slot and generation, and validation also checks the owning instance and resource type. Service identities are independently generation-tagged. Never wrap exhausted generations. The first fixed profile permits four services and eight handles each; M4 will add graph-level admission fixtures and package metadata.

Extend the experimental API to revision 2 for timers and simulated GPIO. Keep descriptor and envelope layouts unchanged. The MCU M1 proof advertises unavailable operations through explicit unsupported callbacks until the full port in M5.

A timed-out native hook requires whole-runtime recovery and retains allocations. A callback that returns an error can instead follow cooperative cleanup. Host scheduling is not a hardware timing guarantee, and native services remain trusted code.

Consequences: callbacks cannot overlap lifecycle hooks, teardown is auditable, and bounded tables are easy to account for. Long callbacks delay that service's other work and must obey deadlines. Periodic timer delivery coalesces missed occurrences. This timer facility does not provide hard real-time interrupt execution.
