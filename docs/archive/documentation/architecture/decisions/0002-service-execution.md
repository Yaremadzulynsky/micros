# ADR 0002: Managed Service Tasks

Status: Selected M0 baseline, 2026-09-05. Resolves D-002; establishes the initial D-003 lifecycle contract.

## Context

Lifecycle hooks, memory budgets, shutdown, and callbacks require a defined execution context before the loader grows into a runtime.

## Decision

Use one managed task per service and serialized bounded init/start/step/stop hooks. Shutdown waits for the current hook; failed deadlines require whole-runtime recovery, not unsafe reclamation. The authoritative state table, priorities, and deadlines are in [services](../services.md#m0-execution-contract).

## Alternatives

A shared event loop saves stacks but lets one faulty callback block every service. An unrestricted per-service main loop complicates uniform lifecycle handling. Forced task termination cannot prove peripheral/callback quiescence.

## Consequences and Evidence

Stacks add per-service cost, but task ownership is explicit. Preemption does not establish hard-real-time guarantees. Host behavior will not emulate MCU scheduling exactly. Hardware timing and watchdog behavior have not been tested; validate in M1/M2.
