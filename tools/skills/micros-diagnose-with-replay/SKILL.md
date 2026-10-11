---
name: micros-diagnose-with-replay
description: Isolate micros producer and processing faults by deploying the replay-source service, running a bounded compatible input sequence, and comparing observed outcomes. Use for controlled reproduction or regression experiments that authorize changing the application.
---

# Diagnose with controlled replay

Read the [replay source contract](../../../services/diagnostics/replay-source/README.md)
and [example workflow](../../../examples/diagnostics/README.md). Establish the target,
exact release and intended behavior with [device access](../micros-device-access/SKILL.md).
Replay changes application inputs and may cause real downstream physical actions.
It is not authorized by a read-only inspection request alone; use existing task
scope and obtain any genuinely missing authorization after preparing a concrete plan.

Choose a hypothesis that controlled input can distinguish. Specify expected
outputs from the consumer's contract/source or the user. Preserve a baseline
capture and release identity. An application restart itself may mask the symptom;
record that separately from the change in input.

Prepare an application that replaces the intended producer with
`services/diagnostics/replay-source/service.toml`, alias `replay`, while retaining
other intended services. Do not leave two producers on the input as an isolation
experiment. Bind its ordinary `output` to the consumer's compatible channel, its
`commands` to ReplayCommand and `status` to ReplayStatus. Add the explicit bridge
publication `replay` and status subscription from the example. Coordination
state/action/event ports are outside this service's scope.

Prepare at most 16 ordered frames (48 encoded bytes each) with an explicit run ID.
Use the exact deployed recipe and review with:

```sh
build/python/bin/python -m micros_tooling.diagnostics.replay \
  --project PATH/TO/UNIT.toml --script PATH/TO/replay.json
```

The helper validates protobuf JSON and embeds the output schema hash. Domain
semantics still require judgment: recorded timestamps, publisher epochs, sequence
numbers and validity flags may be rejected by a consumer. Do not substitute host
receipt time for acquisition time or silently rewrite recorded values. The sample
script in this repository is synthetic and demonstrates delivery to a probe only.

Use the [installation procedure](../micros-diagnostic-services/SKILL.md) to preview
and install when in scope. Start a downstream evidence collector, then execute
with `--device NAME_OR_ID --output NEW_EVIDENCE.jsonl`. The runner preloads and
acknowledges every frame before START; scheduling occurs on the MCU. A late frame
beyond the configured budget fails the run instead of generating unbounded catch-up.
One run is allowed per service activation; rearming requires a planned application
restart. Do not automatically repeat a whole-graph restart to obtain a convenient result.

On an uncertain write, timeout or changed activation, stop issuing commands and
inspect status/evidence. The client does not cancel an already armed sequence when
it exits. Duplicate START is idempotent, but a new run ID or redeployment is not a
safe substitute for determining what happened. Already published actions cannot
be rolled back by restoring software.

Compare the same input sequence across releases when investigating a regression.
`phase=3` and the expected publication count establish replay publication, not
consumer processing or physical success. Require the relevant independent output
observation; use existing optical IR self-test or external measurements when
appropriate. Report supported conclusions and unresolved alternatives. Restore the
exact saved application after the temporary experiment and verify its identity.
