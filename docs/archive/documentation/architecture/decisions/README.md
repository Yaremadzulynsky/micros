# Architecture Decisions

- [ADR 0001: Platform and language](0001-platform-and-language.md): D-001 initially resolved for serial bring-up; ADR 0008 records the Feather BSP.
- [ADR 0002: Execution](0002-service-execution.md): D-002 execution direction; ADR 0005 and M2 record lifecycle validation.
- [ADR 0003: Experimental ABI](0003-experimental-abi.md): D-004 interface established for the prototype; image strategy follows in ADR 0004.
- [ADR 0004: M1 fixed-slot loader](0004-m1-fixed-slot-loader.md): experimental MCU image/placement strategy.
- [ADR 0005: Host runtime ownership](0005-host-runtime-ownership.md): lifecycle, timer quiescence, generation-aware resources, and ABI revision 2.
- [ADR 0006: Bounded IPC](0006-bounded-ipc.md): channel publication, cursor/loss semantics, and protobuf codec.
- [ADR 0007: Service packages](0007-service-packages.md): immutable packages, deterministic admission, and local management.
- [ADR 0008: Feather runtime](0008-feather-runtime.md): FreeRTOS integration, fixed service slots, and board GPIO profile.
- [Historical backlog](backlog.md): original decision list retained for traceability. Status here supersedes original open wording.

D-005/D-006 are addressed by runtime ownership and bounded IPC; D-007 by packages; D-008/D-010 by [M6 activation and recovery](../../milestones/M6.md); D-009 by [M7 management](../../milestones/M7.md). These resolutions cover prototype scope, not memory isolation, signed code or kernel OTA. Current ABI/configuration changes are documented in [configuration](../../CONFIGURATION.md). Use sequential `NNNN-short-title.md` records with status, context, decision, alternatives, consequences, and evidence. Update the authoritative topic when revising a decision.
