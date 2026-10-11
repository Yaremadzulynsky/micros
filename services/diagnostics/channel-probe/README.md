# Channel probe

A schema-bound observer for an **ordinary** stream or latest-value channel.
Select this manifest as `probe`, bind `subscriptions.input` to the channel under
investigation and `publications.report` to `probe_report.proto`. It compiles against
that input's generated protobuf type; it does not assume a PinSample or sensor.
Coordination state/action/event ports use a different API and are not supported.
Use a latest-value channel with depth 1 and max_payload 128 for the report.

Configuration is defined in `service.toml`: a nonzero `run_id`, `duration_ms`
(10–60000), `max_messages` (1–100000), `reads_per_step` (1–8), and
`report_interval_ms` (10–60000). Capture starts when this service starts. It ends
at the duration or message limit, or on a nonrecoverable read error. Final results
remain in the report channel; the service performs no further reads.

`messages` counts successfully decoded messages. `missed_events` counts loss
notifications, **not the number of messages lost**. `decode_errors` counts malformed
protobuf reads. A valid default/empty protobuf message counts as a message.
`max_silence_us` includes startup and trailing silence, measured at the probe's
reads within its observation window. It is not source publication cadence,
end-to-end latency, or proof that another consumer received a message. Values
retained before probe start may be read as backlog. Latest-value channels may
intentionally replace intermediate values without a loss notification.

`reason`: 0 observing, 1 duration, 2 message limit, 3 read failure. `done=true`
means the probe has finished, not that the application passed a behavioral test.
`last_error` preserves the last decoder/read error. Both timestamp fields and
silence are MCU monotonic microseconds; graphs from different boots/devices must
not be combined as a common clock.

For remote evidence, expose `probe.report` through the bridge (or deployment
`[streams.probe_report]`). The published port is `report` on deployed
service name `diagnostic.channel-probe`. Use the collector described in the
[examples](../../../examples/diagnostics/README.md).
