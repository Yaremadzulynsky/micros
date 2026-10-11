---
name: micros-diagnostic-services
description: Configure, build, deploy and verify diagnostic services on a micros device, or implement missing instrumentation using the native service SDK.
---

# Install diagnostic instrumentation

Run from the repository root. Read [deployment](../../../docs/archive/documentation/DEPLOYING.md), [operations](../../../docs/archive/documentation/OPERATIONS.md), and the chosen service's documentation and source before editing its configuration.

## Choose instrumentation that exists

- [DHT](../../../examples/services/dht/README.md) implements a Feather ESP32 V2 GPIO27 DHT11 diagnostic with readings and explicit failure logs. Its register access and clock requirements are ESP32-specific; it is not a generic sensor or arbitrary-pin driver.
- [Logger](../../../examples/services/logger/README.md) consumes button events and reports delivery latency and missed messages. It does not sample pins itself.
- [Pin monitor](../../../services/pin-monitor/README.md) implements bounded digital/raw ADC polling; [network bridge](../../../services/network-bridge/README.md) exposes declared ordinary channels through resident management.
- [Diagnostic services](../../../services/diagnostics/README.md) provide a schema-bound channel probe, a triggered input recorder, and a controlled replay source. Read the selected instrument's contract and catalog entry before configuring it. Fixed source aliases are `probe`, `recorder`, and `replay`; these are not arbitrary-port or unrestricted hardware access tools.

Identify the board through `./micros devices` and `./micros status -d NAME_OR_ID --json`. Inspect its complete `units/<device_id>.toml`, selected hardware bindings, current grants and service sources. Do not use a demonstration board ID as the target. Establish actual wiring and supported electrical/input modes before changing GPIO behavior; ask for missing wiring information when it determines whether the operation is valid.

## Prepare the complete application

Edit the selected unit file, preserving its other intended services. Network deployment does not fall back to the root `micros.toml` template. Paths in a unit file are relative to that file. Include the service's build, configuration schema, capabilities and channel contracts, not just an `enabled` flag copied from another board.

For composed deployments, edit the service manifest/application/board/deployment
sources and emit a new reviewed unit recipe. For existing operational units, edit
the exact authored recipe selected for the device. Do not substitute an example
graph for the user's running application. Preserve an explicit starting release
for restoration. Check total service slots, channel depth/payload budgets and
diagnostic timing limits before proposing installation.

Check the bridge's schema budget too: each service package supports at most four
schemas. Exposing replay commands/status, probe reports and both recorder outputs
requires five schemas; split those experiments into separate reviewed deployments.
Changing bridge port contracts changes its service identity, so select a fresh
bridge version when an existing name/version has already been deployed with
different contracts. Do not change the resident ABI to bypass application limits.

Pins must have compatible board bindings and ownership grants. Do not take a pin from a running owner simply to observe it: consume that owner's published data or instrument that service. Check platform/base budgets and clock requirements. Do not remove unrelated services to make room without user direction.

For new instrumentation, read [SDK](../../../docs/archive/documentation/SDK.md) and use existing service examples. Keep state in the service arena, work bounded, and resource acquisition/release within the managed lifecycle. Use generated named resource and IPC helpers. Define bounded schemas and explicit invalid/loss semantics. Deployment compares graph content hashes; source, contract, and tunable changes do not require a service version bump. Use versions as descriptive release labels.

## Preview, deploy and verify

1. Run `./micros deploy -d NAME_OR_ID --dry-run`. Review the resolved application, resource admission, exact base compatibility, package identities and whole-application restart scope. Resolve errors before mutation.
2. When installation is within the user's request, run `./micros deploy -d NAME_OR_ID`. If the request was only to prepare or review, deliver the diff and preview instead. Service deployment can stop the complete graph during staging; it is not a per-service restart or base flash.
3. Wait for confirmed deployment, then inspect status and logs. Verify the actual diagnostic outcome: valid measurements, expected events, or explicit failure reasons. A healthy process or checksum alone does not validate sensor calibration.
4. On an ambiguous result, inspect status before retrying. Use [operations](../../../docs/archive/documentation/OPERATIONS.md) for recovery or exact-release rollback; do not overwrite a pending trial blindly.

For temporary instrumentation, record the starting release and agreed observation window. Restore the intended application when removal is part of the task, then verify it. Report changes, deployment confirmation, diagnostic evidence and limitations separately; never claim a hardware check that was only built locally.

Use the shared-lease collector in the [diagnostic examples](../../../examples/diagnostics/README.md)
for device-generated reports. Do not mix it with direct bridge-cursor readers on
the same port. Capture duration ending is not a diagnostic pass: inspect the
instrument's terminal state and preserve gap, error and partial-result evidence.
