---
name: micros-diagnose-signal-quality
description: Investigate noisy, stuck or intermittent micros input readings using the bounded signal-recorder service or existing producer measurements. Use for signal acquisition and trigger-based diagnosis, not high-speed logic analysis.
---

# Diagnose input signal quality

Identify the actual device, deployed release, sensor contract and physical wiring
using [device access](../micros-device-access/SKILL.md). Separate the requested
quantity: electrical digital level, raw ADC count, decoded sensor reading and
processed output are different observations. Inspect error/validity fields and
units before interpreting zeros, repeated values or gaps.

If no symptom was supplied, follow the device-access skill's default health survey
and inspect the already published signals. Do not require the user to identify
which subsystem is broken before measuring what the running application exposes.

Map any suspicious reading back to the physical pin, its owner and the function
under investigation before prioritizing it. An undocumented ADC input varying
between zero and nonzero values has no established expected signal; report that
uncertainty without treating it as the cause of an unrelated fault. An anomaly on
one input cannot diagnose another path without a demonstrated dependency.

When a first capture establishes that acquisition progresses without errors,
extend it only to test a specific hypothesis (for example, a suspected dropout
period). Otherwise return to the device-access functional test plan. Use
[system diagnosis](../micros-diagnose-system/SKILL.md) to choose a discriminating
functional test instead of substituting a longer trace. A static digital input does not distinguish
idle hardware from a disconnected data wire; apply a known stimulus and observe
the actual response through its owning service.

Read the [signal recorder contract](../../../services/diagnostics/signal-recorder/README.md).
Choose between published data and a physical diagnostic:

- If the running owner already publishes useful data, capture it without taking
  its hardware. A recorder cannot acquire a pin owned by another service.
- If raw acquisition is required and available, select the recorder as `recorder`
  with exactly one input grant named `signal`. Establish the actual wiring and
  supported input mode; do not infer voltage suitability from a pin name.
- If the owner must be replaced, state that intervention and preserve the complete
  original release. Use the [installation procedure](../micros-diagnostic-services/SKILL.md)
  only within the authorized task. Check the plan: adding instrumentation can require whole-application activation.

For the existing-data path, use the [shared capture procedure](../micros-device-access/references/capture-access.md)
and evaluate progress, validity and gaps against the producer's declared cadence.
For example, the pin monitor publishes the `samples` port. If this evidence answers the question, report it directly. The
recorder configuration and batching steps below apply when a recorder experiment
is needed; they are not prerequisites for inspecting existing measurements.

Choose a run ID, sampling interval, total duration, trigger and pre/post counts
from the hypothesis. Supported triggers are first valid sample, sampled digital
rising/falling edge, or a value above/below an explicit threshold. An edge requires
two valid observations; invalid readings break continuity. Analog mode is raw
ESP32 ADC1, not calibrated voltage. Polling cannot establish that every pulse was
captured; if the question needs faster edges, report the instrumentation gap.

Expose both `records` and `status`, and start their shared collectors as described
in [the examples](../../../examples/diagnostics/README.md). Retain both evidence files.
Records are batches of up to four nested `samples`, not one electrical sample per
network message. Flatten chronologically by nested `index`; verify all indices
0..total-1, run identity, acquisition timestamps and any device/viewer gap events.
A console batch-progress trace is not the signal waveform.

Distinguish no trigger before timeout, partial post-trigger capture, invalid
readings and skipped scheduled scans. `done=true` means all retained samples were
published, not necessarily collected remotely. A full finite capture does not
prove that unobserved intervals were fault-free. Do not interpolate across invalid
samples or infer electrical edges from skipped polls.

Use [measurement plotting](../micros-pin-graphs/SKILL.md) only after validating the
capture. Relate observations to the original hypothesis, record plausible
alternatives, and identify an external measurement when it is needed to distinguish
them. Restore and verify the original release after a temporary intervention.
