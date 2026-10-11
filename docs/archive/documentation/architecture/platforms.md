# Platforms

> Historical architecture discussion and milestone resolutions. The [V1 architecture](../../v1-architecture.md) and [implemented feature matrix](../V1.md) take precedence over original proposals below.

Status: Working architecture. Original direction and review proposals are preserved below. The M0 contract, where present, takes precedence for the initial implementation; other proposals remain unaccepted.

## 2. Architectural Layers

```text
┌──────────────────────────────────────────────┐
│              Application Services            │
│ Sensors • Controllers • Application Logic   │
├──────────────────────────────────────────────┤
│                   micros SDK                 │
│ Service API • IPC API • Hardware APIs       │
├──────────────────────────────────────────────┤
│                System Services               │
│ Wi-Fi • OTA • Logging • Drivers • Bridges   │
├──────────────────────────────────────────────┤
│                 micros Kernel                │
│ Lifecycle • IPC • Memory • Capabilities     │
├──────────────────────────────────────────────┤
│                 HAL Contract                 │
├──────────────────────────────────────────────┤
│          Board / Platform Support (BSP)      │
│ ESP32 • STM32 • Linux • macOS • ...         │
└──────────────────────────────────────────────┘
```

### HAL vs. BSP

The **HAL is a contract**, not a particular implementation. It defines the primitive operations micros requires from a platform.

A **BSP implements that contract** for a particular target.

For example:

```text
micros HAL
    ├── ESP32 BSP  -> ESP-IDF / hardware
    ├── STM32 BSP  -> STM32 HAL / hardware
    ├── Linux BSP  -> POSIX/Linux APIs
    └── macOS BSP  -> host OS APIs
```

This allows micros and its services to be compiled for a desktop host for development, simulation, testing, and CI.

The HAL should expose generic primitives such as GPIO, UART, SPI, I2C, timers, flash/storage, networking primitives, interrupts, and other platform facilities required by the kernel.

Device-specific concepts such as `read_temperature()` do **not** belong in the HAL.

---

## 15. Portability

Only platform-specific layers should need substantial changes when porting micros.

A desktop target is a deliberate architectural goal:

```text
same service source
      │
      ├── compile -> ESP32 micros
      ├── compile -> STM32 micros
      └── compile -> Linux/macOS micros
```

This enables much of the service graph to be developed and tested on a normal computer before deploying to a microcontroller.

Hardware that does not exist on the desktop can be simulated, mocked, or mapped onto host resources through the BSP.

---

### 19.9 Platform Boundary and Distributed Semantics

**Open:** the minimum HAL contract versus optional platform features.

**Proposal:** distinguish mandatory execution primitives from optional peripheral/network facilities. The HAL should not require every BSP to implement every peripheral. Unsupported features must be discoverable and cause explicit admission or API failures.

Platform-specific driver stacks may remain BSP dependencies. Their memory use, scheduling, and callbacks must be included in the execution/resource model; moving them below the HAL does not remove those costs.

**Established direction:** a bridge may expose remote communication through the service-facing IPC abstraction.

**Proposal:** preserve a common API while exposing disconnection, loss, duplication, and stale data where relevant. Do not promise identical local and remote delivery guarantees. Discovery, routing, transport selection, and loop prevention remain later design work.

---


## M0 Platform and Toolchain Selection

Selected baseline:

| Component | Selection |
| --- | --- |
| MCU | Connected ESP32-PICO-V3-02 revision v3.0; ESP-IDF target `esp32` |
| Board profile | `connected-pico-v3-02`: serial-only bring-up, no peripheral pin assumptions |
| Platform substrate | ESP-IDF v5.5.2 and its bundled FreeRTOS |
| Implementation | C17 kernel, HAL, initial SDK, and first service |
| Host | macOS arm64, Apple Clang 21.0.0; POSIX threads and native dynamic loading in M1 |
| Build | CMake >= 3.24 and Ninja; ESP32 uses ESP-IDF's CMake integration |
| Developer scripts | Python >= 3.10, standard library unless a dependency is explicitly pinned |

ESP-IDF v5.5.2 is a deliberate reproducible baseline, not a claim to be the newest release. Its matching cross compiler must be installed using that SDK's tooling in M1; the older local compilers are not substitutes. See the [official release](https://github.com/espressif/esp-idf/releases/tag/v5.5.2) and [ESP32 FreeRTOS contract](https://docs.espressif.com/projects/esp-idf/en/v5.5.2/esp32/api-reference/system/freertos_idf.html). SDK task stack arguments use bytes; verify all wrapper conversions against the pinned version.

Observed host tools: CMake 4.2.3, Ninja 1.13.1, Python 3.10.9. Existing local ESP-IDF registrations refer to older 5.2–5.4 environments; M0 does not install or alter them. The selected SDK is not yet build-validated.

### Board Scope and Evidence

The [board profile](../../esp32-m1/boards/connected-pico-v3-02/README.md) records the serial observations. USB exposes `USB Single Serial`, VID 0x1a86/PID 0x55d4; this does not identify a carrier board. M0 selects the actual connected board with a deliberately restricted serial-only profile. Carrier name and peripheral mapping remain open for M5, not prerequisites for M1's serial loader proof. No LED/GPIO pin, flash mode, PSRAM capacity, or partition layout is inferred from the adapter.

Mandatory platform contracts cover task execution/join, monotonic time, waiting/wakeup, synchronization, memory-class allocation, executable placement/synchronization, diagnostics, and fatal recovery. Peripheral and network facilities are optional. M0 defines the boundary; HAL function declarations follow the M1 evidence rather than speculatively mirroring ESP-IDF.

## M1 Validation Update

The selected SDK and compiler have now been installed, built, and tested on the MCU. The [M1 record](../milestones/M1.md) supersedes M0's unvalidated-toolchain status. The platform adapter uses GNU17 for ESP-IDF inline assembly; service sources remain C17. Carrier identity and peripheral pin mapping are still unresolved.
