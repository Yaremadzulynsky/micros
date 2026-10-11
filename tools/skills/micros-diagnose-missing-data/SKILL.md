---
name: micros-diagnose-missing-data
description: Diagnose missing or stale micros application data by inspecting the producer/consumer path and, when authorized, installing the channel-probe service. Use when a sensor, service or consumer stops reporting.
---

# Diagnose missing application data

Use [device access](../micros-device-access/SKILL.md) to establish the explicit
device, deployed release and current status. Inspect the actual declared path and
message schema; a local unit file may differ from the deployed recipe. Read the
[channel probe contract](../../../services/diagnostics/channel-probe/README.md) before
choosing its observation window and interpreting its counters.

If the user has not specified a symptom, start with the device-access skill's
default health survey. Establish that data was expected in the observation window
before treating silence as a fault. Event-driven IR traffic may correctly remain
idle for days; periodic telemetry should progress according to its configured
cadence. Use [shared capture/access diagnosis](../micros-device-access/references/capture-access.md)
for an existing exported path before installing a probe or switching API routes.

For event-driven hardware, explicitly plan a known stimulus and expected response.
No requests means execution has not been tested; no response to an observed request
is different evidence. Follow [system diagnosis](../micros-diagnose-system/SKILL.md)
to select a test along the actual input/processing/output path. Polling an idle channel for longer cannot replace
that functional test.

Follow the evidence along the path:

- An unreachable device has unknown application state: distinguish authentication,
  server connectivity and device presence before installing instrumentation.
- A stopped/failed producer requires lifecycle/error evidence. A Running service
  can still produce no valid readings; inspect progress, source and failure logs.
- Advancing producer counters with stale consumption calls for declared-binding,
  backlog, consumer and routing checks. Aggregate runtime loss counters are not
  proof of which consumer missed a message.
- Healthy local data with stale remote capture calls for bridge/server diagnosis.
  Do not conflate capture loss with producer or application-consumer loss.

When another ordinary-channel subscription can distinguish hypotheses, select
`services/diagnostics/channel-probe/service.toml` as alias `probe`, bind `input`
to the existing channel and expose `report` through the bridge. Preserve other
services. It consumes two handles and one service slot; an added bridge consumes
another slot. It cannot probe coordination state/action/event ports. Use the
[installation procedure](../micros-diagnostic-services/SKILL.md) within the user's
authorized scope; installing the probe restarts the application graph and can
change the fault being investigated.

Set an explicit nonzero run ID, duration, message limit and bounded reads per step.
Choose the duration from expected producer behavior; do not invent a universal
message-rate threshold. Start the shared report collector promptly using the
[example commands](../../../examples/diagnostics/README.md). Keep the final report,
stream gap events and device/base/graph provenance together.

Interpret the evidence conservatively:

- `messages=0` after a completed window means no decodable message reached this
  probe in that window. It does not identify a broken physical sensor.
- `decode_errors` means structurally malformed reads, not out-of-range physical values.
- `missed_events` counts notifications, not lost messages. Latest-value replacement
  can be intentional. The probe may initially read backlog retained before it started.
- `max_silence_us` is silence at the probe's reads, including initial/trailing
  silence; it is neither source sample period nor consumer delivery latency.
- A missing terminal report, capture gap, changed activation or failed probe means
  the investigation is incomplete. Preserve that evidence rather than declaring success.

Report what is established, the remaining explanations and the smallest next
experiment that distinguishes them. Stop when the missing evidence requires wiring
information or external instrumentation. Restore the saved application after an
authorized temporary experiment and verify the restored release explicitly.
