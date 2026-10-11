# Vision and Principles

> Historical architecture discussion and milestone resolutions. The [V1 architecture](../../v1-architecture.md) and [implemented feature matrix](../V1.md) take precedence over original proposals below.

Established direction, not a claim of implementation. Detailed implementation contracts live in the topic documents.

## 1. Vision

micros is a lightweight, service-oriented operating system for microcontrollers.

The central abstraction is the **service**. Applications, device drivers, networking components, and other higher-level functionality are independently managed services rather than functionality baked into the kernel.

micros should provide:

- Linux/systemd-like service lifecycle management.
- Independent deployment of services.
- A stable, language-agnostic native ABI.
- Deterministic resource usage suitable for microcontrollers.
- Protobuf-only inter-service communication.
- Hardware portability through a HAL/BSP boundary.
- Desktop-hosted micros targets for development and testing.
- Eventually, transparent communication between services on different devices.

The kernel should provide **mechanisms, not application policy**.

---

## 16. Core Design Decisions

1. **Service-oriented architecture:** independently managed services are the primary unit of software.
2. **Systemd-like lifecycle, not container emulation:** start/stop/install/update/log services without attempting to reproduce Docker.
3. **Native, stable ABI:** WASM is not required as the foundation.
4. **Language agnostic at the ABI boundary:** source language is a toolchain concern.
5. **Uniform service lifecycle interface:** every service is managed through the same contract.
6. **HAL contract + per-platform BSP:** hardware-specific implementation stays below micros.
7. **Mechanism in kernel, policy in services.**
8. **Generic hardware primitives:** micros does not need a new kernel build for every sensor.
9. **Deterministic memory:** service budgets are known before runtime; uncontrolled heap growth is avoided.
10. **Reboot/relayout is acceptable:** simplicity is preferred over implementing virtual-memory-like complexity.
11. **Persistent state belongs in storage, not service RAM.**
12. **Installed != loaded:** flash may contain more services than can simultaneously reside in RAM.
13. **Protobuf-only service IPC.**
14. **No shared service pointers as the IPC model.**
15. **Kernel-owned bounded channels.**
16. **Sequence numbers detect slow/missed stream consumption.**
17. **A dead subscriber must not stall the system.**
18. **Schemas/channels are service metadata, not kernel definitions.**
19. **Schema compatibility is checked by deployment tooling.**
20. **Local and distributed IPC should eventually share one abstraction.**
21. **Minimal independent recovery image provides a path back from a broken main image.**
22. **Desktop-hosted micros is a first-class development target.**
23. **No kernel OTA in v1:** remote updates apply to services only; kernel/HAL/BSP/bootloader/recovery updates require physical flashing.

---

## 18. Current Mental Model

The system should eventually feel something like:

```text
$ micros service list
imu-driver       running
motor-control    running
telemetry        stopped
logger           running

$ micros service stop imu-driver
$ micros service install ./imu-driver.pkg
$ micros service start imu-driver
$ micros logs imu-driver
```

Underneath that simple interface:

```text
service package
      ↓
manifest validation
      ↓
memory + capability allocation
      ↓
native service loader
      ↓
uniform service lifecycle
      ↓
protobuf IPC channels
      ↓
HAL
      ↓
BSP
      ↓
hardware
```

That is the current micros architecture direction.

---

