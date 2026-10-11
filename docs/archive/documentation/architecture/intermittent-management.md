# Management over intermittent links

Proposal · 2026-09-07 · Not implemented

**Recommendation:** separate management semantics from transport. Make commands and transfers survive disconnection; retain HTTPS, then validate UDP and framed serial adapters. Treat QUIC as optional.

The target is slow, intermittent packet delivery across different interfaces. UDP requires IP; the shared abstraction should therefore be datagrams, not UDP sockets. Low bandwidth alone does not disqualify TCP. Long outages, short contact windows and small frames are the stronger constraints.

## Current gap

The relay reuses HTTPS connections. It dispatches requests at most once and retries result delivery. Unfinished commands become unknown after server restart; pending work is not replayed. Deployment uses bounded requests and a device lease. These policies protect against blind retries but do not provide durable offline delivery. See [server behavior](../../../../src/server/README.md) and [validation](../reviews/management-relay-validation.md).

## Options

| Option | Benefit | Cost / limit | Suggested role |
|---|---|---|---|
| HTTPS/TCP | Existing implementation; reliable ordered delivery | Connection setup and timeout recovery; requires IP | Keep for ordinary networks |
| QUIC | Connection migration; independent streams; faster setup | Still uses TLS and connection state; requires a path supporting 1,200-byte UDP payloads, potentially through lower-layer fragmentation; embedded footprint unmeasured | Evaluate for capable IP links [1][2] |
| Message protocol over datagram adapters | Fits small frames and non-IP interfaces; operations survive transport changes | Must implement bounded delivery, pacing, recovery and persistence correctly | Recommended architecture |
| Bundle Protocol v7 | Standard store-and-forward model for disconnected networks | Adds protocol and integration scope beyond direct device management | Revisit if disconnected intermediary relays are required [3] |

QUIC does not replace durable command tracking. An expired connection or reboot still requires application recovery. Its optional 0-RTT data also needs replay-safe application behavior. [1][2]

## Proposed design and tradeoffs

| Component | Proposal | Tradeoff |
|---|---|---|
| Adapter | Expose send/receive, maximum payload, backpressure and link hints. Support framed serial separately from IP. | Link availability is advisory; successful send does not prove delivery. |
| Commands | Prefer `ensure_running(digest)` and `ensure_stopped`. Include stable ID, payload digest and expected state generation. | Desired state simplifies retries; reboot and other one-shot actions need explicit recovery rules. |
| Persistence | Server retains pending intent; device journals accepted mutations and outcomes. Same ID with different contents is rejected. | Flash wear and storage require quotas, compaction and a defined retention horizon. |
| Stale work | Reject older generations; use deadlines where trusted time exists. Define supersession and cancellation. | Generations establish order, not age. Clockless devices cannot enforce absolute expiry alone. |
| Transfers | Address content by digest; send MTU-sized chunks; acknowledge ranges and resume missing data. | Smaller chunks add headers and acknowledgments. Larger windows improve throughput but consume RAM. |
| Scheduling | Prioritize commands/results over bulk data; pace traffic with bounded windows, adaptive retry and backoff. | Conservative pacing increases completion time. Reliability must not saturate a shared link. |
| Activation | Receive and verify the complete candidate before stopping services; then activate transactionally. | Requires storage and runtime changes: current staging stops the graph. Measure flash-write impact while services run. |
| Security | Use an established message-security construction; bind identity, operation and payload. Persist replay/nonce state safely across reboot. | Key lifecycle and recovery add complexity. Evaluate OSCORE if adopting CoAP semantics; do not invent cryptography. [4] |

Keep transport reliability separate from operation completion: a packet acknowledgment means receipt, not successful execution. Reliable adapters should reuse their own loss recovery; datagram adapters need bounded retransmission. Both retain command-level reconciliation.

Do not promise exactly-once execution. A crash between an effect and its journal commit creates ambiguity. Resolve it through atomic commits, repeatable desired-state operations, or inspection of actual state. Commands without those properties must report an uncertain outcome.

## Delivery plan

1. **Define the contract:** command states, generations, retry horizon, storage limits and crash recovery. Add it over existing HTTPS first.
2. **Build UDP and framed serial adapters:** exercise status, desired state and resumable upload. Serial demonstrates that the abstraction does not depend on IP.
3. **Test failure recovery:** loss, duplication, reordering, long delay, outages and device/server resets—including reset between execution and result persistence.
4. **Measure on ESP32:** peak RAM, flash footprint, persistent writes, bytes per completed command, transfer goodput and recovery time. Compare HTTPS and UDP before adding QUIC.

Acceptance: acknowledged durable work survives restart; stale commands cannot reverse newer intent; interrupted uploads resume; control traffic progresses during uploads; queues and retries remain bounded.

Before fixing packet formats, choose the smallest supported payload, expected bitrate, longest outage, duplex behavior and storage budget. These determine whether fragmentation and acknowledgment costs are acceptable. No transport makes an oversized update practical over an insufficient contact window.

## Sources

1. [RFC 9000 — QUIC](https://www.rfc-editor.org/rfc/rfc9000.html): streams, migration, idle timeout and minimum datagram size.
2. [RFC 9001 — TLS for QUIC](https://www.rfc-editor.org/rfc/rfc9001.html): security and 0-RTT replay constraints.
3. [RFC 9171 — Bundle Protocol v7](https://www.rfc-editor.org/rfc/rfc9171.html): intermittent connectivity and store-and-forward delivery.
4. [RFC 8613 — OSCORE](https://datatracker.ietf.org/doc/html/rfc8613): constrained message security and reboot recovery.
