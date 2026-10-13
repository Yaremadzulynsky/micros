# ADR 0001: Initial Platform and Implementation

Status: Selected M0 baseline, 2026-09-05. Resolves D-001 within serial-only bring-up scope.

## Context

The user selected the connected ESP32. Native loading is the main feasibility risk; the implementation should expose it early with minimal runtime/toolchain dependencies.

## Decision

Use the connected ESP32-PICO-V3-02 through a serial-only board profile, ESP-IDF v5.5.2, C17, and CMake/Ninja. Use macOS arm64/Clang for the first host target. Exact details live in [platforms](../platforms.md#m0-platform-and-toolchain-selection).

## Alternatives

Rust offers stronger memory-safety tools but adds language integration work to the first Xtensa loader experiment. C++ adds runtime features that M1 would need to restrict. A new scheduler or bare-metal BSP expands scope beyond service loading. These remain possible future choices.

## Consequences and Evidence

The first SDK producer is C; ABI interoperability with another language remains an M8 gate. Board peripherals remain disabled until identified. Serial identification and host tool inventory are recorded; the selected IDF release exists upstream but is not installed or validated by M0. Compiler and executable-format feasibility remain M1 work.
