# Bounded signal recorder

Select as `recorder`. It owns exactly one input grant named `signal`, polls that
input, keeps a bounded pre-trigger ring, collects a requested post-trigger tail,
then publishes the frozen capture. It cannot attach to another service's owned
pin. Instrument that owner or temporarily replace it within the authorized task.

Bind `records` to `capture_record.proto` (stream, depth 8, max_payload 256) and
`status` to `capture_status.proto` (latest, depth 1, max_payload 128). Expose both
through the existing network bridge. At most 32 chronological records are emitted
once; retain sufficient downstream capacity and start collecting promptly.

| Setting | Meaning |
| --- | --- |
| `run_id` | Nonzero experiment label; also record device/base/application identity |
| `sample_interval_ms` | 10–60000 ms; late polls coalesce and increment `skipped_scans` |
| `duration_ms` | 10–60000 ms, including waiting for the trigger and post-trigger acquisition |
| `analog` | 0 digital, 1 raw ESP32 ADC1 input (GPIO32–39 if exposed) |
| `trigger` | 0 first valid reading; 1 sampled rising edge; 2 sampled falling edge; 3 value >= threshold; 4 value <= threshold |
| `threshold` | Raw ADC count 0–4095, or digital 0/1; no calibrated voltage conversion |
| `pre_samples` | 0–15 readings retained before the trigger |
| `post_samples` | 0–16 additional readings after the trigger; trigger reading is separate |

Rising/falling modes are for digital input. The first reading cannot establish
an edge; invalid readings break edge continuity. Level triggers can fire on the
first valid reading. Invalid samples are retained with `error` and a zero
placeholder; they must never be plotted as zero measurements.

`reason=1` means the requested post-trigger count was acquired; `reason=2` means
the time limit ended acquisition. A timeout without a trigger retains the final
pre-trigger window, possibly zero records. `done=true` means all retained records
were published. It does not prove that a remote viewer collected every record;
verify indices 0..total-1 and stream gaps. A deadline during the post-trigger tail
produces a partial capture with reason 2. Trigger metadata remains in `status`.

Polling is not a logic analyzer and cannot promise detection of short pulses.
Skipped-scan counts describe missed scheduled polls, not missed electrical edges.
ADC reads are sequential raw conversions with no accuracy/calibration claim.
A failed acquisition setup or report publication appears as a runtime failure.

Records are emitted in up to eight batches of at most four samples, fitting the
existing eight-message channel depth. Flatten each batch’s `samples` array and
verify each nested `index`; the status port reports progress, not a signal
waveform. Use each nested sample’s acquisition time when plotting.
