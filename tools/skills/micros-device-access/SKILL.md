---
name: micros-device-access
description: Discover micros devices, run a bounded board health survey, and diagnose runtime or management connectivity issues. Use for requests such as check this board or find what is wrong, including when no symptom is specified.
---

# Access a micros device

Run commands from the micros repository root. Read [terminal operations](../../../docs/archive/documentation/OPERATIONS.md) for command semantics and [deployment](../../../docs/archive/documentation/DEPLOYING.md) for identity and transport details. Check `./micros --help` and the relevant subcommand help when platform support or flags are uncertain.

## Identify and inspect

1. Run `./micros devices` to read the management server's live roster. Select the user's device by authenticated identity; use explicit `-d NAME_OR_ID` on subsequent commands. If several boards fit the request, ask which one before targeting hardware.
2. Run `./micros status -d NAME_OR_ID --json` and `./micros logs -d NAME_OR_ID --json`. Inspect the returned shape before scripting against it. Use `./micros doctor -d NAME_OR_ID` when connectivity or base compatibility needs diagnosis.
3. Relate the reported hardware identity to `units/<12-lowercase-MAC-digits>.toml`. Inspect that file for intended services and wiring. Runtime liveness alone does not establish correct sensor readings or application behavior; check task-specific logs or observations.

The configured server is the default remote route: boards connect outward to it. A local saved profile is not the live roster. USB is an explicit onboarding/recovery route; read [onboarding](../../../docs/archive/documentation/ONBOARDING.md) if requested. Determine the actual platform before applying ESP32-specific instructions.

## Default health survey

For “check the board,” “find what's wrong,” or “check that yourself,” start this
survey without requiring the user to name a failed function. Use the deployed
services and contracts to determine which functions can be checked. A supplied
symptom narrows the survey; its absence does not block observation.

1. Save status and recent logs under a new ignored `build/` investigation directory.
   Record device/base/release identity, activation state, service results, network
   state and available resource counters. Inspect failed/stopped services and
   pending updates before selecting additional instruments.
2. Map the deployed producers, consumers, bridge ports and hardware owners. Treat
   the local unit file as intended configuration until it agrees with the current
   release. Classify channels as periodic, event-driven or request/response using
   configuration, schemas and source. An old IR frame is inconclusive if no IR
   activity was expected; a Running service is not proof of correct behavior.
3. Take a second status snapshot after a bounded observation window. Start with
   10–15 seconds for ordinary telemetry, adjusted to cover several configured
   sample periods. Compare service steps, publications, errors, loss and resource
   changes only within the same boot and activation. Use deltas rather than old
   lifetime totals. If a source is too slow for the chosen window, report that
   coverage limit rather than declaring it stalled.
4. Capture useful measurements already exported by the running owners through the
   [shared collector](references/capture-access.md). Compare acquisition freshness,
   sequence progress, validity/errors and gaps with the producer's contract.
   Follow [signal quality](../micros-diagnose-signal-quality/SKILL.md) for suspicious
   readings, or [missing data](../micros-diagnose-missing-data/SKILL.md) when an
   expected publication or consumption path does not progress.
5. Make a functional test plan for each unverified subsystem: its physical pins
   and owner, a controlled stimulus, expected response, evidence source, and what
   each possible result would distinguish. For event-driven hardware, no recent
   events means a stimulus is needed to test it; it is not a reason to omit that
   subsystem. Follow [system diagnosis](../micros-diagnose-system/SKILL.md) to
   choose discriminating tests across hardware, software and integration paths.
   Check stimulus delivery separately from the subsystem's response.
6. Run the smallest discriminating tests within the user's scope. Honor existing
   authorization to test hardware; do not ask again merely because observation
   now needs a stimulus. Account for physical effects, ownership and any required
   graph replacement. If a concrete test needs missing authorization or physical
   help, prepare it and explain exactly what is needed while continuing independent
   checks. A general survey alone does not authorize replacing the application.
7. Report observed failures, functions that showed expected behavior, and tests
   still blocked or inconclusive, each tied to evidence and an observation window.
   “All services Running” establishes runtime liveness, not functional health.

Prioritize evidence connected to the subsystem under test. Before extending a
trace, state the hypothesis and the new observation that would distinguish it.
Do not repeatedly graph a noisy, undocumented input just because it is easy to
capture while another subsystem remains functionally untested. A longer trace
with the same unexplained variation does not localize a fault.

Ask a focused question only when a concrete next test depends on information
unavailable from the board/repository, such as actual external wiring or expected
physical behavior. Explain that dependency and the findings already obtained.
Do not repeat a broad symptom question after the user asks you to investigate.
When further observation cannot distinguish the remaining explanations, report
that limit and the specific experiment needed; do not loop on unchanged status.

## Diagnose without changing the application

- Distinguish an offline board, authentication failure, certificate mismatch, incompatible base, and a live runtime with unhealthy application services. Preserve certificate verification; do not replace credentials to work around a connection error.
- Status and logs remain useful without a local base ELF. Deployment needs the exact authenticated base identity and matching artifacts; do not substitute a newly compiled ELF.
- A stale local pairing is a tooling mismatch, not evidence of faulty board firmware. Server-backed deployment/rollback can fetch the exact live base by its authenticated hash. Name the command that failed: the legacy local `release` export path can reject a stale pairing even when server-backed checks succeed. Do not prescribe a reflash from that error alone.
- For rejected capture routes or login problems, follow [capture access](references/capture-access.md) before switching transport or concluding the base needs an update.
- Logs are bounded and volatile. Preserve repeated messages, loss events and boot changes. Use `--follow` only for a bounded observation window and stop the process afterward.
- After an interrupted update, inspect status before deciding on recovery. Do not blindly repeat activation. `stop`, `recover`, `reboot`, and rollback affect the whole application or device; use them when the user's task authorizes that change, not merely to inspect it.
- Credentials, private state and base artifacts belong in ignored `.micros/` or other private storage. Do not copy tokens, certificates or private ELF contents into reports or commits.

Report the selected device, observed runtime/application state, relevant evidence, and any unresolved connectivity issue. Distinguish observed facts from diagnosis.
