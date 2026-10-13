---
name: micros-pin-graphs
description: Plot real micros pin-related or sensor diagnostics from captured readings, preserving timing, validity and data gaps. Use for signal or sensor charts and to identify missing acquisition support.
---

# Graph measured diagnostics

Run device CLI commands from the application directory; run SDK helper scripts from the SDK root as their references specify. First identify what the requested chart represents: raw electrical pin levels, debounced button events, sensor measurements, or delivery latency. These are different signals; do not substitute one silently.

## Establish an actual data source

Read the exact deployed configuration, producer source and message schema. The
[pin monitor](../../../services/pin-monitor/README.md) provides bounded digital/raw
ADC samples; the [network bridge](../../../services/network-bridge/README.md) exposes
declared channels. The [signal recorder](../../../services/diagnostics/signal-recorder/README.md)
provides finite triggered captures. Do not invent a `micros pins` command,
arbitrary-pin ownership, calibrated voltages, or sample-rate guarantees.

For diagnostic captures, use the shared-lease collector in the
[examples](../../../examples/diagnostics/README.md). Recorder events contain batches:
flatten the nested `samples` array using its indices, error fields and acquisition
timestamps. Validate the full index range against `total` and the companion status
report. The console's batch-progress trace is not the raw waveform. Preserve device
and viewer loss events; do not compete with manual bridge readers on the same port.

Existing sources include [DHT diagnostic logs and local environment IPC](../../../examples/services/dht/README.md) and [button latency logs](../../../examples/services/logger/README.md). Use `./micros logs -d NAME_OR_ID --json` for a snapshot, or a bounded `--follow` capture. Inspect the CLI output and producer's actual formatting before writing a parser. Keep raw capture data so the chart can be reproduced. Stop the capture process when its observation window ends.

If the requested signal is not exported, explain the specific missing acquisition path. If implementation is in scope, follow [SDK](../../../docs/site/service-api.md) and the pin-monitor ownership constraints to add instrumentation, build and verify it before collecting. Otherwise report the gap and the available measurements. Do not produce synthetic data as a hardware result.

## Preserve measurement meaning

- Label each trace with device identity, pin or sensor, quantity and units. Use digital step plots for sampled binary state, and continuous axes for measured quantities. Debounced event traces are not raw GPIO captures.
- Use producer timestamps when present. Device monotonic time is not UTC; segment at boot/publisher restarts. Different boards' monotonic clocks are not synchronized.
- If logs lack sample timestamps, use sample index. Host receipt time may be shown only when explicitly labelled as receipt time; buffered logs can arrive together. Do not reconstruct precise sample timing from a nominal interval.
- DHT IPC consumers must check `valid` and freshness. Failed attempts contain zeroed measurement fields that are not zero measurements. Convert tenths only for fields encoded in tenths; logs may already print physical units.
- Preserve loss, invalid samples and reboot boundaries as gaps or annotations. Do not deduplicate identical readings, interpolate across missing intervals, or imply that polling captured every edge. State any downsampling used for display.

## Deliver a reproducible chart

Use an available plotting library to save a shareable PNG or SVG and a normalized CSV under an ignored `build/` output directory. Retain the parser or plotting script alongside the raw capture when one was needed. Include provenance and time-axis semantics in the output. Keep credentials and private device artifacts out of chart files.

Check parsed values against raw records, counts of valid/invalid samples, units and restart segmentation. Open the rendered chart to check axes, legends and gaps. If there are no valid samples, report the acquisition failure rather than drawing a successful-looking chart. Return artifact paths, capture scope and the interpretation supported by the measurements.
