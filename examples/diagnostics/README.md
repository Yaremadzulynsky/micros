# Diagnostic service examples

These are reviewable complete recipes, not deployment instructions for an
unidentified board. `channel-replay.toml` runs replay + probe + bridge (3 slots,
no GPIO). `signal-recorder.toml` runs recorder + bridge (2 slots) and declares
Feather input GPIO38; verify actual board/wiring/ownership before adapting it.
A production application must retain its other intended services and resource
budgets. Do not deploy these example graphs as a shortcut to add one instrument.

## Build and review locally

From the repository root:

```sh
./micros config --project examples/diagnostics/channel-replay.toml
./micros generate --project examples/diagnostics/channel-replay.toml
./micros build --project examples/diagnostics/channel-replay.toml \
  --firmware PATH/TO/MATCHING_BASE.elf --output build/diagnostic-review
```

For a real device, preserve its exact starting release, adapt its unit recipe,
preview the complete graph and deploy through the normal CLI when authorized.
Deployment pauses all application services. The service manifest catalog is in
[`services/diagnostics/`](../../services/diagnostics/README.md).

## Collect device-generated evidence

The updated server exposes the existing shared capture leases to authenticated
operators at `POST /v1/streams/DEVICE_ID` (open/read/close). It uses the same
permissions, boot/activation fencing, fan-out and loss events as console capture;
no extra device connection or competing bridge cursor is created. No credentials
are written into evidence. An ESP32 base with IPC stream protocol 1 is required.

Once the diagnostic has been deployed and its view metadata archived:

```sh
build/python/bin/python -m micros_tooling.diagnostics.collect \
  --device NAME_OR_ID --service diagnostic.channel-probe --port report \
  --seconds 15 --output build/investigation/probe.jsonl
```

Recorder ports are `records` and `status` on `diagnostic.signal-recorder`; collect
both when trigger outcome and capture completeness matter. Run concurrent collectors
as needed; independent diagnostic readers can share these streams. Do not mix them with manual
`channels read`/`pin_monitor` readers on the same underlying bridge port.

Capture files contain provenance, decoded samples, explicit device/reader gaps,
and a capture-end record. Numeric protobuf uint64 values are JSON strings to
preserve precision. Capture termination is not the diagnostic's pass/fail result.
An empty capture is inconclusive. Start readers before the relevant event; a new
reader of an already active stream starts at its current cursor, not historical
samples. A service's final latest report may already have been drained by another
reader. A server restart or device/application change requires a new capture.
Durations are bounded between reads; an in-flight server long poll can add up to
10 seconds (and a network request can time out). Capture interruption preserves
partial evidence and closes the reader lease, or records expiry-based cleanup.

## Prepare and run controlled replay

Review encoded LOAD/START commands without contacting a device:

```sh
build/python/bin/python -m micros_tooling.diagnostics.replay \
  --project examples/diagnostics/channel-replay.toml \
  --script examples/diagnostics/replay.json
```

`replay.json` specifies a run ID and up to 16 `{after_ms, message}` frames. Messages
use the selected output schema's protobuf JSON format. The script generator checks
fields, encoding bounds and ordered offsets and binds commands to the schema hash.

After authorized installation, use the **exact deployed unit recipe**:

```sh
build/python/bin/python -m micros_tooling.diagnostics.replay \
  --device NAME_OR_ID --project /path/to/application/units/DEVICE_ID.toml \
  --script build/investigation/replay.json \
  --output build/investigation/replay-result.jsonl
```

The runner opens a shared replay-status reader, loads and acknowledges every frame,
then starts once and waits for completion. Start a probe collector separately to
observe downstream delivery. A transport failure leaves an unconfirmed outcome;
inspect retained evidence and runtime status before any further action. Stopping
the client does not cancel frames already armed on the device. Restoration of the
original application is a separate explicit operation using its saved release.
