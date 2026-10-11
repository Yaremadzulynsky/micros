# Deployable diagnostic services

These are native MCU services, selected and deployed like other application
services. LLM skills choose an instrument, configure a bounded experiment, and
interpret its evidence. Host helpers only encode commands and collect the
service's results through the existing management connection.

| Instrument | Alias | Question it can answer | Required ports/resources |
| --- | --- | --- | --- |
| [Channel probe](channel-probe/README.md) | `probe` | Does this subscription receive decodable messages, with what observed silence/loss? | Ordinary `input` subscription, `report` publication; no GPIO |
| [Signal recorder](signal-recorder/README.md) | `recorder` | What input readings surrounded a trigger? | One exclusive input GPIO, `records` and `status` publications |
| [Replay source](replay-source/README.md) | `replay` | How does a consumer behave with a controlled sequence of compatible inputs? | Ordinary `commands` subscription, `output` and `status` publications; no GPIO |

Use the fixed aliases above: source includes their generated APIs. Select the
manifest in an application, or adapt the complete recipes in
[`examples/diagnostics/`](../../examples/diagnostics/README.md). Schemas are under
`src/sdk/protos/diagnostics/v1/`; the machine-readable catalog is `catalog.json`.

The services have bounded arena state, no dynamic allocation or networking, and
bounded work per step. Reports are typed protobuf messages. A service remaining
Running after completing its observation is expected; inspect its terminal report.
A report publication failure is a runtime failure, not a successful diagnosis.

Adding instrumentation stages and restarts the whole application. Preserve the
starting release, compare pre/post restart observations, and restore the intended
application after an authorized temporary experiment. Adding the bridge consumes
one additional slot. Do not remove unrelated services to make room or take a pin
from another service merely to observe it.

## Agent workflows

- [Missing data](../../tools/skills/micros-diagnose-missing-data/SKILL.md): install a probe on a declared ordinary channel.
- [Signal quality](../../tools/skills/micros-diagnose-signal-quality/SKILL.md): bounded input acquisition with explicit electrical and timing limits.
- [Controlled replay](../../tools/skills/micros-diagnose-with-replay/SKILL.md): replace a producer, preload frames, run once and compare observations.

System status, lifecycle/heap counters and logs remain resident diagnostics; no
extra service is needed to read them. The [IR driver](../../examples/services/ir-capture/README.md) supports a specialized physical loopback
instrument when explicitly configured; a completed replay alone is not
proof of any physical output.

## Validation scope

Host tests exercise production service code with generated protobuf APIs and
simulated clocks/transport/GPIO. ESP32 review builds exercise native image creation
and package/graph admission. These checks do not establish physical pin accuracy,
edge-capture bandwidth, scheduling jitter on hardware or an actuator's behavior.
Shared-lease collection requires an ESP32 base advertising `ipc_stream: 1` and the
server's operator stream endpoint. Other target/hardware combinations need their
own validation.

The [Feather hardware validation](../../docs/archive/documentation/reviews/diagnostic-skills-feather-validation.md)
records a controlled replay/probe check and a finite digital-input capture on
ABI 0 revision 7, including evidence and the limits of those experiments.
