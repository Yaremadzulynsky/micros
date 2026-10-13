# ADR 0004: Fixed-Slot Native Loader Experiment

Status: Selected M1 implementation strategy; hardware execution evidence is recorded separately in the milestone report.

## Context

The first MCU experiment needs independently compiled native execution without first implementing general Xtensa relocation or a filesystem execute-in-place design.

## Decision

Reserve executable/data slots in the base firmware and link service images against their exported addresses. Use an explicit bounded envelope and direct descriptor lookup on MCU; use a wrapped native dylib on host. The full contract lives in [the native image profile](../native-image.md).

## Alternatives

A relocatable ELF loader handles arbitrary placement but expands validation and relocation scope. Position-independent output still requires investigation of Xtensa literals and data references. Flash execution introduces mapping and storage constraints. None is ruled out for a later multi-service loader.

## Consequences

Services update independently while the base layout stays fixed. A changed slot layout requires rebuilding the service image; one service slot is supported. The runtime has no relocation table, and code must fit the reserved internal IRAM. This satisfies a narrowly scoped independent-loading experiment, not the complete v1 deployment design.

The service remains C17. The ESP-IDF-facing platform compilation uses GNU17 because the SDK headers use GNU assembly syntax; this extension is confined to the platform boundary.

## Evidence

The compiler is Espressif GCC 14.2.0 (`esp-14.2.0_20251107`). Disassembly shows windowed-ABI `entry`, `callx8`, and `retw` instructions. The linked service has no undefined symbols or runtime relocations. Actual execution, resource measurements, and rejection results belong in the [M1 record](../../milestones/M1.md).
