# Native ABI

[service.h](include/micros/service.h) defines experimental ABI 0 revision 7: target IDs, SDK table, argument lifetime, and lifecycle descriptor. It is a native in-memory contract, not a package header or a stable released ABI.

See the [service contract](../../../docs/archive/documentation/architecture/services.md#minimal-abi-profile) and [host build checks](../../../docs/archive/documentation/BUILDING.md). No kernel-private or platform SDK types cross this boundary. M1 validated the MCU calling convention; M2/M3 append bounded timer/GPIO/IPC callbacks, with explicit unsupported stubs in the MCU proof harness.

Revision 5 replaces public IPC callbacks with an opaque private dispatch pointer. Service code includes generated port interfaces; only the kernel, generated SDK implementations and internal test fixtures include `internal/micros/ipc.h`. Earlier bases and packages must be rebuilt.
