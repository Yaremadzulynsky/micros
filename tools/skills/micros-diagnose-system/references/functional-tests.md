# Examples of discriminating functional tests

These illustrate reasoning patterns, not fixed diagnoses or universal commands.
Select tests from the deployed contract and actual physical setup.

## Healthy processes, no physical receive events

Model the path as command delivery → transmitter → physical path → receiver →
decoded event. Check each stage rather than interpreting idle counters as success.
One known transmission with a matching receive event tests the chain. Transmit
completion without reception leaves emission, alignment, receiver power/ground/data
and decoding as alternatives. A known-working external source tests the receiving
side independently; an external receiver tests emission independently.

For the repository's Feather IR example, verify the live bindings before using
the checked-in mapping: GPIO27 is RX, GPIO25 is TX, and GPIO34 is an unrelated
analog monitor. GPIO34 variation provides no evidence about the receive data wire.
A disconnected digital input can retain an idle-looking level without read errors.
Use the IR owner or suitable external instrumentation; 10 ms GPIO polling cannot
establish correct sub-millisecond pulse decoding.

The current [`board.ir-coordination`](../../../../examples/services/ir-coordination/src/service.c)
uses typed actions. Its [result](../../../../src/sdk/protos/coordination/v1/ir_action.proto)
includes cumulative transmissions and optical matches; compare deltas and correlate
the result with the fresh invocation/activation. TX completion alone does not prove
light was emitted. A missing matching RX localizes a path, not an unplugged cable.

[`micros_tooling.fleet.coordination status`](../../../../src/micros_tooling/fleet/coordination.py)
observes routes; it does not submit a fresh action. If a required route is missing,
follow [coordination test setup](coordination-tests.md) to create it within scope
and then exercise the compatible publisher. The
[hardware proof collector](../../../../tests/hardware/coordination.py) also only
observes and assumes a specific two-board demo. Inspect the actual publisher's
trigger. Historical optical self-test recipes and appliance commands belong in
the owning application repository. The legacy `board.ir-capture` interface differs
from typed coordination; its command/result helpers are not interchangeable with the
coordination service. Choose a compatible existing trigger or prepare a reviewed
one-shot test application within scope; do not blindly redeploy a historical graph,
restart another board's controller, or assume a code is harmless to nearby devices.

## Fresh telemetry, incorrect processing result

Map acquisition → publication → subscription → processing → result. Advancing
producer counters establish activity, not consumer correctness. Probe the actual
input boundary and compare its schema, validity and freshness with the consumer's
contract. Supply known compatible values with a predicted output through replay
when authorized. If the expected output appears, investigate the upstream data
or its domain semantics. If it does not, inspect consumer binding/processing/output
and the observer. A schema-valid replay with stale timestamps is not a valid control
when the consumer rejects old measurements.

## Irregular graph, apparently normal acquisition

Map the graph to its actual source and compare sequence/acquisition time against
device counters and capture gaps. Regular valid device samples with viewer gaps
point toward observation/delivery. Invalid device samples point toward acquisition
or the source. Zero is a possible measurement, a default invalid placeholder, or
an idle input depending on the contract. Establish which before interpreting it.
Once a capture separates those cases, more of the same graph will not identify
an undocumented physical connection. Test a known input, a relevant trigger or a
specific connection instead, with the expected result recorded beforehand.
