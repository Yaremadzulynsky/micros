---
name: micros-diagnose-system
description: Localize micros hardware, service, data-path and integration faults by forming hypotheses and running discriminating functional tests. Use after initial device inspection, especially when runtime health is normal but the function is untested or a broad investigation has no named symptom.
---

# Diagnose a system through experiments

Use [device access](../micros-device-access/SKILL.md) for initial identity, status
and logs. Reuse evidence already collected; do not repeat the survey just because
this skill was selected. The task is to localize the failing function and test
explanations, not to accumulate whichever measurements are easiest to obtain.

## Build a model of the actual system

Identify the deployed components, their responsibilities and dependencies from
the live release, configuration, contracts and source. Trace each relevant path:
input or command → acquisition/delivery → processing → output → observable effect.
Include external hardware, shared power/ground, clocks, network and resource
ownership where applicable. Map each measurement to its actual component/pin/port.
Do not infer this topology from a suggestive name or a noisy graph.

For each function, record what should happen, what initiates it, what evidence is
available, and whether it has been exercised in this investigation. Derive expected
behavior from the contract and configuration; mark undocumented behavior unknown.
For a broad “I broke something” request, survey the declared functions rather than
assuming the first unusual reading identifies the fault. Prioritize failing
functions, then untested functions with useful low-cost tests. Constant or unusual
measurements without a known expectation are weak leads.

Runtime liveness, advancing steps, valid encoding and a successful command
acknowledgement establish different facts. None alone establishes a correct
physical measurement, processing result or external effect. Event-driven systems
need a stimulus before silence can count as evidence of failure.

## Choose a discriminating test

Keep a short list of plausible explanations for the observed failure. For each,
state supporting evidence, contradictory evidence and a result that would weaken
it. Include observation/transport failure when the evidence path itself is unproven.
Avoid inventing precise probabilities or treating every imaginable cause equally.

Before the next measurement, write a compact test record in the investigation:

- **Question and alternatives:** which explanations does this test separate?
- **Intervention or observation:** exact input, relevant component/port, starting
  release, run identity, and any prerequisite such as known wiring or a live peer.
- **Expected outcomes:** what should be observed under each explanation, through
  which independent evidence, and within what contract-based time window?
- **Execution and cleanup:** bounded duration/work, physical effects, existing
  authorization, and restoration when a temporary change is required.

Prefer tests that split the remaining explanations while changing little state.
Observe adjacent stages to find where an expected result first disappears or
becomes incorrect. Choose an appropriate experiment rather than always installing
the same diagnostic service:

| Question | Useful experiment |
| --- | --- |
| Has this function actually been exercised? | Apply one known compatible stimulus and verify it reached the intended component before judging the response. |
| Does data reach the next stage? | Compare producer and consumer evidence; use a channel probe at the uncertain boundary. |
| Is the producer or downstream processing wrong? | Substitute a known valid input/replay and inspect the consumer's output against its contract. |
| Is the actuator/transmitter or receiving path wrong? | Use an independent known-working input source or output observer; a loopback alone tests several components together. |
| Is an intermittent failure correlated with a condition? | Capture around a relevant trigger or change one controlled condition, with timestamps, errors and gaps retained. |
| Is the collector itself losing data? | Compare device-side progress with capture sequence/gap evidence before blaming acquisition. |
| Did a software change cause the regression? | Run the same bounded input and output check on exact releases, controlling restart/configuration differences. |

If more data would leave all current explanations equally plausible, choose a
different experiment. Extend a trace only to resolve a specific uncertainty, such
as a suspected recurrence interval. Do not let an unrelated anomalous input displace
testing of the function the user asked to investigate.

## Use capabilities that match the test

- [Missing data](../micros-diagnose-missing-data/SKILL.md) and the channel probe
  test delivery on declared ordinary channels; coordination ports differ.
- [Signal quality](../micros-diagnose-signal-quality/SKILL.md) selects existing
  acquisition or the bounded input recorder, respecting ownership and bandwidth.
- [Replay](../micros-diagnose-with-replay/SKILL.md) supplies controlled ordinary
  messages; its success must be paired with a downstream outcome check.
- [Capture access](../micros-device-access/references/capture-access.md) diagnoses
  observation-path problems. [Instrument installation](../micros-diagnostic-services/SKILL.md)
  handles application changes when a suitable test needs a deployable instrument.

Inspect the actual exposed interface and helper implementation before invoking a
test. A status/proof collector may only observe retained results; it does not
necessarily trigger new work. A historical test may assume a different service,
protocol, wiring, version or graph. Do not fabricate commands or treat an interface
mismatch as a component failure. Read the relevant [worked examples](references/functional-tests.md)
when choosing among stimulus, substitution and independent-observer tests.

Use existing authorization to run tests and continue independently where possible.
If a useful test lacks a trigger or observable result, name that missing capability
and prepare the smallest implementation when development is in scope. Otherwise
identify the exact external stimulus, measurement or user input needed. Do not
silently replace the application or expand testing to another device. Conversely,
do not stop at “untested” when an available test is already within the user's scope.

## Complete the test prerequisites

An authorized functional test includes setting up its necessary compatible routes,
observers and stimulus path within the authorized devices and effects. Identify
what is missing and complete that setup; do not merely report “no coordination
route,” “no reader” or “no commands” and end the investigation when you can resolve
it within scope. Use existing authorization rather than requesting it again.

For a cross-device coordination test, follow the
[coordination setup procedure](references/coordination-tests.md): verify compatible
live endpoints, preserve the existing route configuration, preview and create a
missing route, verify admission, then trigger and observe fresh work. For a local
connection or ordinary IPC channel, use its actual interface instead of creating
an unnecessary server route. Inspect retained or pending actions before connecting
endpoints because admission can immediately make earlier intent deliverable.

A missing or offline publisher is a separate prerequisite from its route. Select
a compatible available stimulus source within scope or prepare the smallest
needed test capability. Do not assume a route retriggers a startup-only producer.
If completion needs a new device, physical action, unavailable contract or expanded
authorization, present the concrete prepared next step and that specific dependency.
Continue any independent tests instead of treating setup failure as a hardware
result. Restore temporary configuration and verify cleanup after the test.

## Update the diagnosis after each test

Preserve input, output, timestamps, errors/gaps and activation identity. Verify the
stimulus was delivered and the observer was functioning. A timeout before either
is established leaves the test inconclusive. Do not automatically repeat uncertain
writes; first determine whether the prior action may already have taken effect.

Compare the observation with the predicted outcomes, then update the explanation
list. Change one variable when isolating a cause, or explicitly account for changes
such as a whole-graph restart that could mask the original failure. A successful
substitution narrows a fault boundary; it need not identify a particular failed part.

Stop when the evidence supports a useful localization or when the remaining
explanations require unavailable evidence. Report the tested path, observed
failure, causes ruled against, still-plausible causes and the smallest next check.
Ask only the concrete question that unlocks that check, not for the user to diagnose
the fault first. Distinguish “localized to this path” from “root cause confirmed.”

After an authorized correction, repeat the same discriminating test to verify the
predicted change, check affected neighboring functions and restore temporary
instrumentation. Preserve the before/after evidence. One successful trial does not
rule out an intermittent fault or establish untested physical performance.
