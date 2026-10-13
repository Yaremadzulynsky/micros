# Device-independent service coordination prototype

Status: experimental, executable contract proposal. This directory does not
change the service ABI, production generator, local IPC, relay, or deployed
firmware. Nothing is flashed or published. The TOML is proposed syntax, not an
input to `micros deploy`.

## Developer contract

Developers define application protobufs and declare a port kind. The runtime
owns identities, revisions, duplicate suppression, and advertisement scheduling.
Application messages contain no device address, transport, or sequencing fields.

| Port | Meaning | Replacement rule | Application responsibility |
| --- | --- | --- | --- |
| State | Current complete snapshot | Newest revision supersedes earlier values | Apply value; handle missing/stale observations |
| Action | Perform this particular operation | Cannot replace an outstanding action | Explicitly complete, fail, reject, or report uncertainty |
| Event | This occurrence may be missed | No recovery advertisement | Accept loss and possible sequence gaps |

The same rules apply when endpoints share a board. Existing bounded local sample
streams remain separate; this proposal does not turn waveform history into state.
Ports needing bounded timing must declare placement/admission constraints later.

See `ports.toml`, `light_target.proto`, `photo_request.proto`, and
`photo_result.proto`. A protobuf's fields cannot determine its port kind.
Application validation still matters: the light service validates 0..100 itself.

Conceptual generated API (not an implemented C ABI):

```c
target_read(&target, &input_token, &observation);
// Apply the target, then publish an observation with an opaque applied token.
reported_set_applied(&actual, input_token);

take_photo_request(&settings, &ticket);       // Bounded, asynchronous.
take_photo_next(&invocation, &settings);      // Executor receives once per ID.
take_photo_complete(invocation, &photo_ref);  // Explicit application outcome.
take_photo_result(ticket, &status, &result);
```

State confirmation is optional. A reported state's `applied` reference identifies
the exact input binding/generation/revision. Reading input does not acknowledge
application. A new applied reference advances the reported revision even if the
actual value is unchanged. This first sketch supports one applied reference per
snapshot; it does not aggregate acknowledgements for several independent inputs.
Bindings must restrict allowed acknowledgement targets in production. Matching
tokens establish the service's report, not independent physical verification.

## Envelope and ownership

`wire.proto` separates runtime metadata from opaque application protobuf bytes.
A binding resolves a logical port contract, its schema identities, authorized
writer/executor, and subscribers. It is not a MCU address. Protocol version, exact
binding generation, direction, kind, and payload bounds must be admitted before
delivery. Transport authentication is required independently of protobuf parsing.
The prototype checks identity/kind/bounds; it does not implement authentication
or the global binding compiler.

Generation is an explicitly installed binding lifetime. Unknown generations are
rejected, never adopted from incoming traffic. Within that lifetime, counters
start at one and never wrap. Losing counter continuity requires an explicit
generation replacement; production tooling must fence the old owner on all
participants before claiming reassignment is complete. This prototype uses exact
preconfigured generations and does not implement distributed reconfiguration.
Ordinary reconnect does not change identity. A restart may retain a generation
only if its relevant counters and records are recovered safely.

The initial cap is 96 application bytes per record. Nanopb computes a maximum of
176 encoded bytes for the complete envelope, including the optional applied
reference. Admission allows at most 192 bytes. These are prototype limits, not
claims that every radio can carry them. Authentication/framing overhead is extra.
A link with a smaller budget must reject the binding or use a separately designed
fragmentation layer. No fragmentation is implemented here.

## State lifecycle

1. State starts unavailable, including for a default-valued protobuf.
2. `set` installs a complete snapshot; changed bytes or applied reference advance
   its revision. Generated APIs should use consistent serialization.
3. Each source advertisement advances a separate refresh counter. Repetition of
   unchanged state does not create another application change.
4. A sink accepts newer advertisements, ignores old/replayed refreshes, and
   rejects inconsistent revisions. Lost intermediate snapshots need no recovery.

The model exposes **receiver observation age**, not proven source freshness.
A never-before-seen packet may have spent an arbitrarily long time in a link or
router. A refresh counter prevents replay from extending observation age, but
does not prove a first-seen packet was generated recently. Therefore a generic
"fresh" API would currently overpromise. End-to-end freshness needs a defined
clock/age bound or challenge/lease protocol before production use. Router caches
must not manufacture refresh counters. Applications needing measurement time
must define that separately from publication identity.

## Action lifecycle

One logical requester, one executor, one outstanding request per binding.
Request IDs are `(binding, generation, sequence)`. Operation type comes from the
port; arguments come from its protobuf. A jump from sequence 10 to 13 is rejected,
not interpreted as three operations with the latest arguments.

```text
request retained -> accepted -> completed | failed | rejected | indeterminate
                     |
                     +-- interrupted recovery -> indeterminate
```

The requester advertises the same request while awaiting an outcome. The executor
advertises its retained status/result. Duplicate requests do not redispatch.
Accepted is not completed. Terminal outcomes cannot regress to accepted, and
conflicting terminal outcomes are rejected. Old requests cannot run again after
the executor has advanced. Completion uses a ticket to reject stale callbacks.

The next sequential request implies the requester observed the preceding terminal
outcome, allowing the executor to replace the retained result. Until then, one
request/result record remains retained, including when there is no further work.
The requester may stop advertisements after completion; the model's `advertise`
method merely makes a record available to an external scheduler. Cleanup without
a next request is deferred. Full result history is not provided.

There are no transport acknowledgements or packet retry timers. Pending action
advertisements are nevertheless application-level retransmission and results are
application-level acknowledgements. Eventual completion requires that execution
can finish and both directions eventually deliver while records remain retained.
Permanent disconnection provides no progress guarantee. Timeout is uncertainty.

## Crash boundary

Production action support must atomically retain acceptance **before application
dispatch**, and retain completion **before advertising it**. The requester must
also recover its pending request, counter, and observed outcome before advancing.
Checkpoint/recovery in `model.py` is an in-memory representation of an executor's
durable record, not a flash journal or requester recovery implementation.

After interrupted execution, the default result is indeterminate: do not silently
redispatch a possibly completed physical action. A photo service could later add
recovery by locating an image stored under its invocation identity. Persistence
alone does not provide exactly-once physical execution. A new request after an
indeterminate outcome must be an explicit application decision, never an automatic
retry with a fresh ID. Deadlines, cancellation, workflow sequencing, and multiwriter
arbitration are intentionally outside this first contract.

## Run and inspect

From the repository root, with the existing pinned development environment:

```sh
build/python/bin/python archive/service-coordination/run.py
```

The runner uses the existing production `compile_schema` checks, creates Python
types from the descriptors, generates static Nanopb C codecs, compiles a native
codec with warnings as errors, and runs deterministic contract tests. All generated
files are temporary. Native maximum-field round trips check every envelope kind;
an oversized byte field is rejected by both the model and the native decoder.

Tests cover lost updates and action outcomes, duplicate requests, replay and
reordering, default/empty state, explicit applied references, generation rejection,
malformed records, counter exhaustion, event gaps, and modeled executor recovery.
They do not establish radio performance, flash crash safety, authenticated routing,
end-to-end freshness, or compatibility with the current service ABI.

## Next integration decisions

1. Review these semantics and generated port operations before reserving ABI fields.
2. Compile service/global declarations into bounded channel and ownership records.
3. Specify source lifetime admission and freshness before automatic reassignment.
4. Add bounded base-runtime retention/scheduling and actual durable action records.
5. Exercise the same contract locally and across a deliberately lossy adapter.

The server should be one routing implementation. Neither protobuf payloads nor
service APIs should require it. A scheduler should coalesce state and budget refresh
traffic per link; no periodic timer or network task belongs in application services.
