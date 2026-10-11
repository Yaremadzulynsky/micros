# Device-independent service coordination

Experimental ABI 7 implementation. Application messages are bounded protobuf;
services declare the meaning of a port and use generated operations. They do not
contain addresses, transport selection, sequence counters, or refresh loops.

```toml
[services.controller.publications.target]
channel = "target"
kind = "state"

[services.controller.publications.operation]
channel = "operation"
kind = "action"
```

The referenced channel must use `policy = "latest"`, `depth = 1`, and
`max_payload <= 64`. Kind is retained in package metadata. Ordinary local stream
channels retain their existing behavior. Coordination admission requires one
publisher; actions also require at most one executor. A subscriber-only graph is
allowed only for declared coordination channels in package admission.

## Generated service callbacks

The preferred C interface uses callbacks and a generated service descriptor.
The existing low-level handle operations remain available for explicit adapters.

For the controller's declared ports, application code calls:

```c
controller_target_message_t target = {.value = 73};
controller_set_target(args, &target);

controller_operation_message_t request = {.code = 0xbb44ff00};
controller_request_operation(args, &request);
```

The controller supplies a terminal callback and its application lifecycle hooks:

```c
static micros_result_t operation_finished(
    const micros_service_args_t *args,
    const controller_operation_result_t *outcome)
{
    // outcome->status is terminal; outcome->message contains the protobuf result.
    return MICROS_OK;
}

static const controller_callbacks_t callbacks = {
    .on_operation_finished = operation_finished,
};
static const micros_service_hooks_t lifecycle = {
    .start = start,
    .stop = stop,
};
CONTROLLER_SERVICE(controller_state_t, 2048, lifecycle, callbacks)
```

`CONTROLLER_SERVICE` replaces the handwritten descriptor and query function. It
keeps `controller_state_t` first in the instance arena, so existing lifecycle hooks
and timer callbacks still see application state through `args->arena`. Generated
bookkeeping follows it; the descriptor includes the total size and alignment in
normal memory admission. There is no global mutable adapter state or heap allocation.

The port name `coordination` is reserved for the generated adapter.

The wrapper opens coordination ports before application `init`, dispatches their
callbacks before application `step`, and closes them after application `stop`, even
if that hook fails. Lifecycle hooks are optional. Every incoming port and outgoing
action requires its typed callback; missing callbacks fail initialization before
any port is opened. Partial port acquisition is cleaned up on failure. Ordinary
GPIO, timers, and local stream handles remain application-owned.

| Port | Generated application operation | Callback member |
| --- | --- | --- |
| State publication `target` | `controller_set_target(args, &snapshot)` | — |
| State subscription `target` | — | `on_target_changed(args, &snapshot, &info)` |
| Action publication `operation` | `controller_request_operation(args, &request)` | `on_operation_finished(args, &outcome)` |
| Action subscription `operations` | `ir_complete_operations(args, action, status, &result)` | `on_operations_requested(args, &request, action)` |
| Event publication `notice` | `service_emit_notice(args, &event)` | — |
| Event subscription `notice` | — | `on_notice_event(args, &event, &info)` |

These names derive from each service alias and port. Callback message, metadata,
and outcome pointers are borrowed only for that callback; copy data that must
survive it. An executor can copy its opaque `micros_action_t` token into application
state and complete later, as the IR driver does after checking its hardware.

Callbacks run serially on the existing service scheduler. A dispatch pass checks
at most one record per port, in declaration order. Request/set/emit never invoke a
callback synchronously. A callback returns `MICROS_OK` or an error; errors propagate
through the normal lifecycle failure path. This is not a transaction across ports.

One action may be pending per publication port. A second request returns
`MICROS_ERROR_STATE`; it is not queued. The adapter ignores accepted progress,
validates result identity, and delivers a terminal callback at most once for that
submission in the current service lifetime. It clears the pending flag before the
callback, allowing the callback to submit the next action. A disconnected executor
can leave a request pending indefinitely: no timeout, retry queue, or fabricated
completion is introduced. Stop closes the adapter without invoking new application
callbacks; existing runtime interruption and restart rules still apply.

State callbacks can skip intermediate revisions. Event callbacks remain lossy;
metadata exposes revisions for application gap detection. The adapter does not
turn either into a reliable event queue. Application hardware state and business
decisions remain in the service. The controller demo now uses a one-shot timer
for its delay, with no coordination phase machine or result polling.

## Low-level operations

| Kind | Publisher operations | Subscriber operations | Meaning |
| --- | --- | --- | --- |
| state | `set` | `read` | Complete retained snapshot; unchanged bytes do not advance revision |
| action | `request`, `result` | `next`, `complete` | One outstanding request and retained outcome |
| event | `emit` | `read` | Latest occurrence, explicitly lossy; router offers each revision once |

All operations are nonblocking and use normal instance-owned handles and resource
permissions. `open` and `close` are generated for every port. Callers supply a
`micros_coord_info_t` to receive opaque identity and status. They copy the invocation
info into `complete`, setting its terminal status; they never increment a sequence.
The initial action contract uses one protobuf schema for requests/results; distinct
request/result shapes can be nested or represented with a protobuf `oneof`.

State may supersede earlier values. Action submission returns `MICROS_ERROR_STATE`
while an earlier request lacks a terminal outcome. Accepted means dispatched to the
executor, not completed. The executor explicitly reports completed, failed, rejected,
or indeterminate. Closing an executing action port marks the retained result
indeterminate. Duplicate requests cannot dispatch twice within a runtime lifetime.
After a new request, `result` returns EMPTY until an outcome for that request is
available; it cannot return the previous request's completion.

The current `read` operation returns new revisions, and EMPTY otherwise. Info's
observation age is receiver-local and is not a source-freshness guarantee. An
application needing a no-update timeout must track its own receipt time. Packet
age across intermittent links, stale-state notifications, durable action journals,
expiration and cancellation are future contracts; they are not implied by these APIs.

## Global bindings

For the composed authoring workflow, start with
[deployment composition](COMPOSITION.md). Its deployment file produces the
complete unit recipes and route file described below using an offline command.

`coordination.toml` names logical `device.service.port` endpoints and references the
unit TOMLs. The compiler checks direction, kind, exact protobuf schema identity,
interface version, and payload bounds. Services remain unaware of those bindings.

```sh
build/python/bin/python -m micros_tooling.fleet.coordination preview
build/python/bin/python -m micros_tooling.fleet.coordination apply
build/python/bin/python -m micros_tooling.fleet.coordination status
build/python/bin/python -m micros_tooling.fleet.coordination clear
```

Preview does not mutate a device. Apply admits routes through the authenticated
operator endpoint `/v1/coordination`; the device-only listener does not expose it.
Admission pins each enrolled device's boot identity, base hash, application hash,
and activation sequence. The base independently checks an opened typed port and
its direction before binding. No synthetic bridge service or extra service slot is
needed for these ports. Local publisher/subscriber ports can communicate through
the same runtime operations without a server binding.

The current compiler checks authored unit contracts and pins the live selections;
it does not yet reconstruct the entire authored graph against archived releases.
Deploy the referenced unit files before admission. Production dynamic discovery
should resolve port contracts directly from the admitted release catalog.

The router lives in the management server, not in a laptop polling script. It uses
the existing outbound authenticated connections. Each turn offers current retained
state or action intent/result; the service itself publishes once. Management work
has priority. Buffers, routes (eight), outstanding transport operations (one per
device), and diagnostic history (128 records) are bounded. Coordination payloads do
not enter the SQLite command journal. There is no queue of disconnected samples.

This first router admits one route per endpoint; network fan-out and multi-writer
arbitration are not implemented. Each service may expose several independently
bound ports. The same application API also works for purely local coordination.

The transport adapter currently exchanges a 48-byte little-endian metadata header
plus at most 64 protobuf bytes through operation 18. It includes format/kind,
source lifetime, revision, result status, and optional applied-state reference.
This compact framing is separate from application protobuf semantics; the earlier
`archive/service-coordination/wire.proto` remains a reference proposal, not the
installed transport encoding. TLS still retransmits internally. There are no
coordination packet acknowledgements or packet replay timers. Action intent and
outcomes are deliberately re-advertised at the application protocol level.

## Restart and loss behavior

A server restart preserves admitted routes and source identity, then rebinds and
reads retained records from the bases. The source's existing epoch is used during
binding, preserving opaque tickets already returned to services. A board restart,
stop, graph change, or activation change fences the route. Old cached requests are
not automatically injected into the new application lifetime.

The current MCU ledger is volatile. Exactly-once physical actions across board
power loss are not provided. Action re-admission after an endpoint lifetime change
requires restarting both endpoint applications so an old pending request cannot
silently execute against a lost ledger. Clearing routes is an administrative
teardown, not an action-recovery mechanism. Inspect unknown physical outcomes before
issuing a new action. Network disconnection alone does not clear the ledger.

`drop_first` in a global route is a development fault injector: it drops that many
eligible advertisements in each applicable direction. State/action advertisements
recover after the drop budget is exhausted. Events are not recovered. Set it to
zero for normal use.

## Hardware demonstration

The ESP8266 unit runs `coordination.controller`: set target 73 once, then submit one
NEC White action (`0xbb44ff00`). The Feather's `board.ir-coordination` consumes target
state and executes the action using its existing GPIO25 transmitter and GPIO27
receiver. Completion requires TX completion and a matching decoded 34-word optical
NEC waveform. Its result contains transmission count, optical-match count, and the
applied target value. The controller checks those fields before logging PASS.

The waveform remains on the local stream; only small intent/result/state messages
cross boards. Pin monitoring and raw IR viewing remain available. The old IR
command/result console API is replaced for this test application; the original
IR service source and schemas remain available for other graphs.

`coordination-wroom.toml` selects the same controller implementation on the WROOM
instead. That unit keeps its existing hello and DHT services. Its target state uses
local channel key 3, whereas the Feather uses key 2; these local keys need not agree.

Feather flash-mapped service code capacity is now advertised as 12 KiB per slot;
fixed physical slot spacing and partition layout are unchanged. Tools use the
base's exported capacity and preserve the old 8 KiB fallback. Writable service
reservations remain independently defined by the base. Service binaries are rebuilt
for the exact new ABI/base identity.

## Validation

```sh
cmake --build build/host -j 6
ctest --test-dir build/host -R 'runtime_lifecycle|ipc_boundaries' --output-on-failure
build/python/bin/python -m unittest discover -s tests/server -p '*_test.py'
build/python/bin/python archive/service-coordination/run.py
```

Production runtime tests exercise transfer between two instances, generation
rejection, duplicate suppression, bounded actions, and interrupted execution.
Router tests exercise controlled loss, offline peers, boot fencing, atomic
configuration, restart identity preservation, and absence of payload journaling.
See the [hardware evidence report](COORDINATION-HARDWARE.md) for actual device outcomes; host tests alone do
not prove an optical transmission occurred.
