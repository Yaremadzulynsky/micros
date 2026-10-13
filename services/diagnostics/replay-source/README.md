# Controlled replay source

Select as `replay` with an ordinary typed `output` publication. Bind `commands`
to `replay_command.proto` (stream, depth 8, max_payload 128) and `status` to
`replay_status.proto` (latest, depth 1, max_payload 128). Add a bridge publication
named `replay` bound to the command channel and a bridge subscription for status.
The complete [example recipe](../../../examples/diagnostics/channel-replay.toml)
contains those bindings. Incoming bridge writes currently require an explicit
recipe; composition's `[streams]` only generates outbound captures.

This is an intervention: output messages may drive a real application's actuators.
Replace the original producer deliberately; leaving two producers connected does
not isolate it. Each activation accepts **one run** identified by a nonzero ID.
There is no clear/rearm command; repeating an experiment requires an explicitly
planned application restart/redeployment and a new evidence record.

1. LOAD slots 0..15 with offsets and protobuf-encoded messages (up to 48 bytes each).
2. Observe the status `loaded_mask`. Identical LOAD retries are idempotent; changed
   content at an existing index is rejected.
3. START with the exact count (1..16). Every slot must exist and offsets must be
   nondecreasing. The MCU schedules offsets relative to START receipt.
4. Observe `phase=3` and the published count, or `phase=4` and the failure evidence.

LOAD and START carry the complete SHA-256 of the declared output schema. The
service rejects mismatches before accepting a command. The generated decoder
validates each message. Structural decoding does not establish domain validity;
recorded timestamps, sequence numbers, validity flags and units must suit the
consumer. The sample script has synthetic values with default timestamps and
only demonstrates delivery to a probe, not a live sensor replacement.

Frames are decoded and published through the generated API; known field values
are preserved but this is not byte-for-byte reproduction of unknown protobuf
fields. There are no physical outputs in the replay service itself.

Configuration: `arm_timeout_ms` (100–600000) bounds the initial loading/arming
window; `max_duration_ms` (1–60000) bounds scheduled offsets; `max_lateness_ms`
(1–5000) stops a run before publishing an excessively late frame. Each step reads
at most two commands and publishes at most four frames. Publish failures stop the
run; already published frames cannot be undone. `max_late_us` measures lateness
at the replay service, not downstream execution latency.

A duplicate START for the same run/count never repeats output. A different run
ID, partial schedule, late LOAD, conflicting slot or schema mismatch is rejected.
`rejected_commands` and `last_error` retain evidence; an uncertain network outcome
must be inspected rather than blindly retried. The host runner does not retry
writes and uses the shared status stream, including boot/activation fencing.
