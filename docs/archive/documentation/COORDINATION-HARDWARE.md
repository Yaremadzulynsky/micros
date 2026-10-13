# Coordination hardware evidence — 2026-09-11

## WROOM → Feather: passed

At 20:17:40 UTC, the controller on WROOM `b0a732c8082c` coordinated with the
IR service on Feather `e89f6d30e1a8`. The server ran the production router from
`server/coordination.py`. The operator admitted `coordination-wroom.toml` once;
no laptop process drove state publication or command retransmission.

The controller called `target_set(73)` once and submitted one action. The router
deliberately discarded the first three state advertisements, three action-intent
advertisements, and three outcome advertisements. Both routes bound successfully,
with zero rejected exchanges in the captured observation.

The Feather's retained protobuf outcome reported:

| Field | Observed value |
| --- | --- |
| NEC code | `0xbb44ff00` |
| Successful transmissions | 1 |
| Matching optical receptions | 1 |
| Applied target value | 73 |
| Outcome | COMPLETED |

The GPIO27 receiver captured and decoded the transmitted NEC waveform; completing
the software TX operation alone was insufficient for a successful outcome. The
Feather logged `COORD IR OPTICAL MATCH` and `COORD IR COMPLETE optical verified`.
The WROOM subsequently logged:

```text
COORD PROOF PASS: remote state 73, one TX, one optical RX, action completed
```

[Machine-readable evidence](evidence/coordination-wroom.json) includes route pins,
base/application identities, source generations, the protobuf payload, injected
loss records, and both boards' relevant logs. The WROOM retained its hello and DHT
services alongside the new controller. The Feather retained pin monitoring and
raw-frame viewing alongside the IR service.

This test used Wi-Fi/HTTPS between boards and the server. IR provided physical
actuation and sensing on the Feather; it was not the inter-board transport. The
test proves recovery from deliberately dropped coordination advertisements and
deduplication within the running application lifetimes. It does not establish
performance on LoRa/laser links or durable exactly-once actuation across power loss.

## Management-server restart: passed

At 20:20:58 UTC, after restarting the management container, the router reloaded
the saved bindings and adopted the bases' retained records. Both routes rebound
without rejection. The Feather retained its boot identity and the same completed
result: one transmission, one optical match, applied value 73. Its log still
contained only one execution. The development loss budgets were applied again.
See [restart evidence](evidence/coordination-server-restart.json).

## Generated callbacks: passed

At 20:50:48 UTC, the migrated `coordination.controller` 1.1.0 and
`board.ir-coordination` 3.1.0 passed the same test on the WROOM and Feather.
Both deployments confirmed on their existing ABI 7 bases. The controller uses
`controller_set_target`, `controller_request_operation`, and
`on_operation_finished`; it has no coordination phase machine or result polling.
The IR service receives state and action callbacks and completes an opaque action
token after the hardware operation.

The current admission discarded three advertisements in each of the state,
request, and result directions. Its completed result again contained target 73,
one transmission, and one optical match. The controller logged PASS.
[Callback implementation evidence](evidence/coordination-callbacks.json) records
these service versions, route pins, current action generation, and device logs.
Base logs can retain earlier application runs; the proof collector now matches
outcomes to the current route generation and checks each current route's drop
budget, rather than accepting old events or cumulative server counters.

## ESP8266 rollout

The original base downloader stalled. A power cycle returned ESP8266
`f4cfa2d08ce3` to its previous ABI 5 base with no pending candidate. A bounded
chunked relay upload subsequently reached roughly 115 KiB before the board again
stopped checking in. The operator received an unknown-outcome timeout; no write or
activation was replayed. The board requires recovery, preferably USB. No ESP8266
cross-board result is claimed.

The final ESP8266 base and controller application both compile successfully. The
prepared base identity is
`449a533d7bdc26ae040ce5da33189d7851eb63df093ed1b6b0d79cd768e679b1`;
this is a build result, not a confirmed device installation.

## Software checks

- Full host build succeeded; all 55 CTest cases passed after the callback migration.
  An earlier parallel run hit the lifecycle test time limit; the isolated rerun
  and complete serial run passed.
- All 68 server tests passed.
- Generated-adapter tests compile real protobuf C code and exercise all six port
  directions, callback errors, partial initialization, instance isolation, busy
  requests, deferred completion, stale outcomes, and callback deduplication.
- The runtime regression covers a second action: its caller cannot observe the
  previous action's completion as the new result.
- The chunked OTA regression verifies byte order/padding and that an uncertain
  write neither replays nor proceeds to activation.

## Reproducing the observation

Deploy the referenced units against their exact ABI 7 bases, then:

```sh
build/python/bin/python -m micros_tooling.fleet.coordination preview --project coordination-wroom.toml
build/python/bin/python -m micros_tooling.fleet.coordination apply --project coordination-wroom.toml
build/python/bin/python tests/hardware/coordination.py --output build/coordination/proof.json
./micros logs -d wroom --json
./micros logs -d feather --json
```

The collector is read-only. Inspect controller logs as well as the collected
executor outcome to establish that completion reached the requester. For a new
physical action test after a board/application restart, restart both endpoint
applications and explicitly re-admit the routes; do not replay an uncertain action.
