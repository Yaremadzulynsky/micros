# Service interfaces in the console

Services can supply a `console.json` next to their source. The ESP32 application
builder compiles its protobuf references and includes a bounded description in the
host `.msp` manifest. The existing deployer sends images and graph data to the MCU;
UI descriptions and schemas stay in the archived packages on the server. No broker,
additional listener, MCU HTTP server, or service-provided JavaScript is needed.

## Try the interface without a board

```sh
build/python/bin/python -m micros_tooling.console.console_preview
```

Open `http://127.0.0.1:8765/console/`, select the simulated workbench and choose
**Interfaces**. Start capture, or try the output-level form. All data and commands
in this local preview are simulated. It cannot contact a physical board.

## Add a waveform

The pin monitor includes this working description:

```json
{
  "format": 1,
  "views": [{
    "id": "pins",
    "title": "Pin readings",
    "kind": "waveform",
    "port": "samples",
    "timestamp": "monotonic_us",
    "epoch": "publisher_started_us",
    "group": "pin",
    "error": "error",
    "series": [{"field": "value", "label": "Reading", "unit": "raw"}]
  }]
}
```

`port` is the service's publication name in its unit recipe. `timestamp` identifies
a 64-bit microsecond counter on the device. Optional `epoch` identifies publisher
restarts, `group` separates pins or other numeric identities, and `error` suppresses
invalid readings when nonzero. Series fields must be singular numbers or booleans.
This initial pin view labels values as raw: digital readings are 0/1 and analog
readings are ADC counts, not calibrated volts. Avoid combining differently scaled
signals on the same plot when comparing their magnitudes.

Declare the ordinary network bridge as a subscriber to that channel. Its own
`console.json` opts it into routing with `{"format":1,"bridge":true,"views":[]}`.
The builder binds each view to one bridge endpoint with the exact same schema.
Missing bridge mappings leave views local; ambiguous mappings fail admission.
Only use the bridge marker on the actual transport service that opens its ports.

Build and deploy the example recipe using the existing ESP32 workflow. Bump changed
service versions under the project's existing immutable-version rules. Deploying
from the CLI registers the views; console release review also registers them.
The server and build environment need the requirements in their respective files.
Older packages without descriptions keep working and show an explanatory empty state.
No live board was deployed as part of developing this interface.

## Add a command form

A service may describe a subscription using `kind: "command"`. A matching bridge
publication receives the form's message. For a proto3 message containing
`uint32 brightness = 1`, a description could be:

```json
{
  "format": 1,
  "views": [{
    "id": "brightness",
    "title": "Brightness",
    "kind": "command",
    "port": "commands",
    "fields": [{"field": "brightness", "label": "Brightness", "min": 0, "max": 255}]
  }]
}
```

Every field must be described; this first form supports uint32, int32, sint32 and
bool (0/1), with integer bounds checked again on the server. The service must
implement the subscription and validate the command itself. Adding this JSON to
Colors alone does not create command handling. Queued means the bridge accepted
bytes, not that the service acted. Use a state publication to observe the result.
Unknown outcomes are not retried automatically.

## Compatibility and limits

- Description format 1 is separate from the service version and channel contract
  version. Metadata is part of immutable package identity; change the service
  version when changing it. Old console versions reject packages with this new
  manifest field; update server tooling before publishing such packages.
- Views are selected by the observed base and confirmed graph hashes. Pending
  trials suppress them. Commands acquire the device selection lease. Stream
  drains instead validate graph and activation generation on the controller for
  every batch, so capture does not hold a deployment lease.
- The MCU does not report a host package hash. Two releases with identical image
  and graph bytes cannot be distinguished on the board. Conflicting descriptions
  for the same base/graph are rejected, rather than silently changing controls.
  A description-only edit may therefore require an application graph change.
  Older label-only clients do not erase already registered views.
- Continuous capture requires resident ESP32 `ipc_stream: 1` support. Update the
  server and resident base; older bases still support manual channel reads and
  commands. The browser explains when streaming firmware is missing.
- The resident worker uploads up to eight events (3000 JSON bytes) per turn,
  using the existing TLS connection. Turns are spaced by at least 50 ms plus
  network delay; empty streams back off to 500 ms. Status is sampled every five seconds. An extra 8 KiB buffer is
  allocated only while streaming. Hardware throughput has not been measured.
- The Pi reads each active port once and fans it out to browser readers with
  independent cursors. Each port retains 256 records in RAM; slow readers get
  explicit gaps. Stream data does not enter SQLite. A lost delivery reply does
  not duplicate samples, and uncertain commands are never replayed.
- Browser storage remains bounded to 400 records and 16 traces per plot. History
  is local to the panel. Manual CLI reads still share the underlying bridge
  cursor; use a separate port for independent CLI inspection during capture.
- Up to eight readers can capture concurrently. Reads long-poll for ten seconds;
  subscriptions expire 30 seconds after their last renewal. Pause/navigation
  sends a close request. A disconnected tab may leave demand until lease expiry.
- Management commands take priority over stream drains. Reboots, changed graphs,
  deployment activity, and offline boards stop the affected capture explicitly.
  Reopen it after management completes or the board reconnects.

Validation includes schema/port binding, protobuf integer precision, stale/trial
selection rejection, stopped services, command bounds, unknown outcomes, browser
capture/control behavior, navigation cleanup, and desktop/mobile rendering. Tests
use isolated data; hardware throughput and physical command effects remain untested.
