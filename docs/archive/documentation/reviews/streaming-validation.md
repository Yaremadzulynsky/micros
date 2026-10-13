# Network bridge streaming validation

The request-driven single-message diagnostic API remains available. Console
capture now uses a leased batch stream on the same resident HTTPS relay connection.
No broker, extra network listener, TLS task, service ABI change, or new service
socket is introduced.

## Implemented behavior

- One drain per port, shared by browser viewers with independent replay cursors.
- Up to eight ordered data/loss events per MCU batch, within 3000 JSON bytes.
  Capacity is reserved before reading, so a full output buffer cannot truncate
  and discard an already-consumed message.
- A 50 ms minimum drain interval; empty streams back off to 500 ms. Active ports
  share turns. Full status is sent every five seconds instead of per sample.
- A temporary 8 KiB resident upload buffer, allocated on first streaming demand
  and freed when streaming ends or a management command takes over.
- Sample bytes stay in bounded Pi memory (256 records/port), outside SQLite and
  the management command journal. Eight reader leases are admitted globally.
- Lost batch acknowledgements are retried with the same ID, without rereading
  the MCU channel. The Pi deduplicates repeated delivery. Command dispatch retains
  its existing at-most-once/unknown-outcome behavior and takes priority.
- Each drain validates the expected graph and activation generation on the MCU
  controller before resolving a service instance. Deployments, restarts and
  expired readers cannot silently remap a capture to another channel.
- Browser pause/navigation closes the lease and aborts its pending read. Abrupt
  disconnects stop demand after the 30-second reader lease expires. Capture must
  be reopened after a reported interruption; no stale command is replayed.

## Evidence

- The server suite covers actual authenticated HTTP upload of a stream frame and
  browser open/read/close, cross-origin/session rejection, shared delivery,
  duplicate acknowledgement handling, slow-viewer gaps, malformed frame bounds,
  restart/selection invalidation, reader expiry, idle backoff, management priority,
  and absence of per-batch database writes or command entries.
- The production C bridge/IPC batch reader is exercised against real host runtime
  channels: eight small records per batch, maximum-size messages across two
  bounded batches, ordered loss events, empty reads, insufficient output capacity
  without cursor consumption, port direction checks and cleanup.
- `main.c` and the production `relay.c` compile with the installed Xtensa compiler
  and an existing ESP32 configuration with `CONFIG_MICROS_RELAY_ENABLED=1`.
  Objects/logs are in ignored `build/stream-validation/`. This is a compile check,
  not a new linked/published firmware release. A generic older build directory
  could not regenerate without its board selection, so it was not used as proof
  of a successful full firmware build.
- Browser checks exercise synthetic eight-event batches, visible gaps, pause,
  command forms, navigation cleanup and desktop/mobile layout using real console
  assets. Existing terminal deployment and single-message bridge client tests
  also pass.

The initial checks above preceded the hardware rollout below. Sustained hardware
throughput, latency, heap headroom under streaming TLS load, and Wi-Fi interruption
recovery still require further on-device measurement. The
50 ms interval is a scheduling bound, not a measured throughput claim. High-rate
acquisition should batch samples in its producer schema and size channel depth
for the expected network delay.

## Hardware rollout — 2026-09-10

- Built complete board-specific ESP32 firmware with ESP-IDF 5.5.2, preserving
  each board's partition table. Published both bases and passed OTA preflight.
- Updated the Pi relay after backing up its application, image and SQLite state.
- Feather (`e89f6d30e1a8`): OTA confirmed base
  `94ba4314fcc480492674ab68a6c9a80c331ca511f120eb008d3387ddd2f3aef8`.
  Redeployed its four services against that base; all report Running/result 0.
  Pin-monitor 1.0.1 and network-bridge 1.0.2 include their console descriptions.
- WROOM (`b0a732c8082c`): OTA confirmed base
  `a743905477ace3e17ea83e397e2d057627550bc2578724fcdcb0301a91669440`.
  Redeployed its existing hello and DHT services; both report Running/result 0.
  This board has no network-bridge subscription configured yet.
- Both report `ipc_stream: 1`, confirmed application activation and no pending
  base trial. Final status snapshots and deployment receipts are retained locally
  under ignored `.micros/stream-rollout-20260910/`.
- An authenticated live console capture on Feather delivered 24 pin samples
  across 8.33 seconds, including initial backlog. It reported 56 overwritten
  readings from before capture, then zero further gaps. GPIOs 34 and 38 retain
  their configured one-second scan interval; this is delivery evidence, not a
  high-rate throughput benchmark.
- The other ESP32 and MKR were offline. ESP8266 remains on its existing firmware;
  this streaming implementation targets ESP32.
