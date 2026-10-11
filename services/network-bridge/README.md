# Network bridge

With [deployment composition](../../docs/archive/documentation/COMPOSITION.md), declare
`[streams.NAME]` with `from = "device.service.port"` in the deployment.
The compiler selects and binds this service automatically for outbound capture.
The explicit recipe format below remains available for existing applications
and inbound network writes.

A small service that opens its declared channel ports for the existing authenticated management connection. The resident transport copies messages through those handles under the runtime lock. The service needs no sockets, timers, extra queues or application-specific decoding.

Use the service alias `bridge`. Declare any number of `publications` (network → local) and `subscriptions` (local → network), within the runtime's eight-handle limit. Bind them to ordinary typed channels; consumers continue to use their generated protobuf APIs. Only the configured ports are opened. The bridge never reads its own subscription cursors; network reads advance them.

[Example recipe](../../examples/network-bridge/micros.toml) declares one port in each direction using the button schema. Copy its service into your deployment, bind its ports to your application's channels and regenerate/build normally. An outbound channel needs an application publisher; an inbound channel needs an application subscriber. No device is automatically deployed by this example.

Use the existing server enrollment and the exact deployed recipe:

```sh
build/python/bin/python -m micros_tooling.communication.channels --device DEVICE_ID --project units/DEVICE_ID.toml read outbound
build/python/bin/python -m micros_tooling.communication.channels --device DEVICE_ID --project units/DEVICE_ID.toml write inbound 08011801
```

Port names are deployment names. The client resolves the bridge's runtime instance index and channel keys from the recipe. Payloads are protobuf bytes encoded as hex; the bridge preserves them without interpreting them. A successful write means queued locally, not processed by a consumer. Remote readers should decode using the channel's schema.

## Continuous console streaming

The console's **Start capture** opens a demand lease on the Pi. The resident relay
then drains the bridge subscription in batches over its existing reusable HTTPS
connection. All diagnostic readers of a port share that one drain and receive their
own replay cursor. Samples are kept in a bounded memory ring on the Pi, not written
to the command journal or a database. The command-line `read` above remains a
single-message diagnostic operation; do not mix it with a live capture on the same
port because it advances the underlying MCU cursor independently.

Streaming requires a newly built ESP32 resident base advertising `ipc_stream: 1`
and the updated server. The service itself needs no new sockets, tasks or ABI.
Older bases retain manual reads/writes; the console explains the required base
update. No devices are automatically flashed by building this feature.

The relay sends at most eight events per batch, capped at 3000 JSON bytes. Loss
notifications occupy an event slot. It waits at least 50 ms between drain turns
and sends full status at five-second intervals. Empty channels progressively
back off to 500 ms between turns, returning to 50 ms when data arrives. Network latency adds to that
interval, and several active ports share turns fairly. Empty reads are bounded,
nonblocking controller operations. This is batched streaming, not a guaranteed
sample rate; high-rate capture should batch acquisition samples in the producer's
schema and be benchmarked on the target hardware.

A stream batch carries a frame ID. Lost delivery replies are retried without
rereading the channel, and the server deduplicates the batch. Byte buffers and
subscription leases are bounded; stopped/expired readers stop demand. Management
commands have priority. Each drain validates the selected graph and activation
generation atomically on the controller, and refuses a pending trial, recovery or
deployment lease. Changed applications and reboots stop capture explicitly.

The only additional resident heap reservation is an 8 KiB upload buffer while a
stream is active, released when demand ends or management takes over. It shares
the existing TLS connection and task. The Pi permits eight readers, keeps 256
records per port, and reports overwritten records to a slow reader without
blocking other readers. Browser reads long-poll for up to ten seconds, and reader
leases expire after 30 seconds without renewal. Pausing sends a close request;
a disconnected browser may leave demand active until its lease expires.

The existing platform-command transport limits writes to 255 command bytes (roughly 120 payload bytes after hex framing) and reads to 256 payload bytes. The client rejects oversized writes without splitting messages. Lost acknowledgements are never retried automatically. Existing resident firmware must support `IPC INFO` protocol 1 and `/v1/platform-command`; older bases need updating before this service can use the connection.

Validation: `network_bridge` exercises production service code against real runtime channels in both directions, including direction enforcement, loss, closed ports and partial initialization cleanup. `network_bridge_client` checks relay framing, bounds and no retry after an uncertain outcome.
