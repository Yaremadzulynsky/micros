# Transport independence and LoRa fleet updates

Status: proposed design, recorded from discussion on 2026-09-08. This is not an implemented contract or a commitment to a particular codec or radio.

## Motivation

Make monitoring, messaging, and service deployment independent of the communication medium. Implement a small adapter for Wi-Fi, BLE, raw LoRa, or another link while keeping application services and management semantics unchanged.

A useful demonstration would be the same application monitored and updated over two different transports without application-code changes. A later fleet demonstration would broadcast an update to roughly 70 devices, using repair traffic only for incomplete receivers. Claims about transport independence should distinguish application-message transport from deployment transport and acknowledge actual deployment downtime.

## Layer boundaries

Proposed responsibilities:

| Layer | Responsibility |
| --- | --- |
| Application services | Hardware behavior and local typed IPC |
| Management/update coordinator | Authorization, transfer lifecycle, package staging, activation, rollback, status |
| Object transfer | Chunk transfer or optional RaptorQ encoding/decoding, progress and resumability |
| Security | Established authenticated communication and release verification |
| Link adapter | Peer addressing, link setup, packet send/receive, payload limits, availability and backpressure |
| Platform driver | Radio and hardware operations |

Start with a packet boundary rather than requiring every medium to emulate TCP. Illustrative primitives are `get_link_info`, `send(peer, bytes, len)`, and `poll(event)`; these are not ABI declarations. Local send completion does not mean remote receipt. Delivery may be lost, duplicated, delayed, or reordered.

Adapters own medium-specific configuration and transmission scheduling. Expose maximum payload and backpressure; do not assume continuous transmission is possible. Radio adapters must not interpret service packages or know about RaptorQ.

Different traffic needs different policies: telemetry can replace stale queued samples, commands need expiry and duplicate handling, and package transfers need reliable completion and integrity verification.

## TLS and security

Transport independence does not prohibit TLS. TLS requires a reliable, ordered byte stream; an adapter stack can supply that over a non-IP link. DTLS preserves datagram semantics and is a candidate for packet links, but does not make application transfers reliable.

Keep the existing Wi-Fi/TLS path while evaluating packet security separately. DTLS on small LoRa packets is not assumed to work without integration: measure handshake and record sizes, configure bounds, and evaluate fragmentation below DTLS separately from package-transfer chunking.

For single-device transfers, a candidate ordering is package blocks → RaptorQ symbols → authenticated packet protection → link adapter. Authenticate received symbols before decoder processing. Final package verification alone does not prevent injected symbols from consuming decoder resources.

One broadcast shared by many receivers needs an explicit group-security design; separate per-device DTLS sessions do not automatically provide secure multicast. A signed release manifest/package should establish release-author authenticity. Confidentiality, sender authentication for symbols, replay protection, key provisioning, and key rotation remain design work. Do not invent a cryptographic protocol as part of the adapter interface.

## Initial LoRa topology

Begin with raw point-to-point LoRa: management server → USB/IP-connected radio bridge → LoRa → micros device. The bridge forwards packets. Prefer end-to-end protection between server and device rather than requiring the bridge to hold deployment credentials.

LoRa is the radio technology; LoRaWAN is a separate networking system and would require a distinct adapter. In particular, LoRaWAN Class A downlinks follow device uplinks in receive windows. Do not assume the proposed raw-LoRa broadcast schedule applies unchanged to LoRaWAN.

Start with periodic status and requested diagnostics instead of continuous verbose logs. Measure payload budgets, airtime, loss, and radio/region constraints before estimating deployment speed.

## RaptorQ fleet transfer

RaptorQ is an optional object-transfer strategy, not a radio driver or security mechanism. It generates original source symbols and additional repair symbols. Receivers can reconstruct a source block from a sufficient set of distinct symbols without obtaining every original packet. Exactly K received symbols for K source symbols is not a guaranteed decode.

Proposed fleet exchange:

1. Repeat an authenticated update announcement with update identity, target compatibility, package size, source-block/symbol parameters, and verification information.
2. Broadcast original symbols followed by repair symbols. The initial discussion used five rounds as an example policy, not a fixed protocol requirement.
3. Send new repair-symbol identifiers across rounds rather than repeatedly sending an identical set. Receivers accumulate symbols across rounds and independently reconstruct bounded blocks.
4. Verified, complete receivers stop decoding that update without immediately acknowledging success.
5. Pause transmission for an explicit repair-request window. Incomplete receivers randomize request timing; requests identify incomplete blocks and may provide progress rather than enumerating missing packets.
6. Broadcast additional repair symbols for requested blocks so multiple incomplete devices can benefit. Bound retries and define subsequent feedback windows.
7. Verify and stage the complete package, then activate under an authenticated command or policy. Include the resulting installed version and health in routine monitoring.

RaptorQ reduces dependence on individual missing-packet retransmissions; it does not remove the need for scheduling, update announcements, security, staging, or activation policy. Duplicate symbols do not add new information. Rounds should have explicit airtime and redundancy budgets based on measured loss.

### Silence is not confirmation

An exceptions-only repair scheme avoids a burst of success responses from 70 devices. However, a device that missed the announcement, is powered off, or failed to transmit its repair request is also silent. Show such devices as unconfirmed until a later heartbeat or query confirms their version. Loss of the return path must not imply successful installation.

### Artifact compatibility

Broadcast is most efficient when receivers consume identical package bytes. Check micros's fixed link slots, target ABI/base compatibility, and per-unit configurations before grouping a fleet. Broadcast by compatible artifact group when packages differ; do not assume all devices can install the same image.

## Runtime integration and feasibility

The initial update coordinator should remain in resident management. A decoder may become a separately compiled service if its resources can be bounded and it remains available throughout staging and activation. The component delivering an update must survive replacement of the application or transport it is updating.

At the time of discussion, management was compiled into the base and the network bridge was documented as a proposal. Existing staging downtime must be inspected before promising that applications continue operating throughout a long radio transfer.

Use an existing RaptorQ implementation if suitable. Native C/C++ support alone does not guarantee compatibility with the micros ABI: inspect allocator, standard-library, threading, code-size, and runtime dependencies. Decoder workspace can exceed source-block data size. Encode on the server and decode bounded blocks on the device; checkpoint progress with appropriate flash-write batching.

Compare RaptorQ with selective chunk retransmission. RaptorQ is particularly attractive when many receivers lose different packets or feedback is expensive; it is not automatically faster or cheaper for a single clean link.

## First experiment and follow-up

1. Encode a real micros package on the desktop.
2. Decode one bounded block on the ESP32 while deliberately dropping symbols.
3. Reconstruct the package and compare its hash.
4. Measure peak decoder RAM, executable size, decode time, and dependency compatibility.
5. Add a real LoRa link and demonstrate status → transfer → verification → activation → version confirmation, including a transfer interruption.
6. Add broadcast rounds and randomized repair windows, then test multiple receivers with different losses, missed announcements, and failed return paths.

The discussion's rough planning estimate was a few days for a codec feasibility experiment if a suitable implementation ports cleanly, and several weeks for an integrated prototype. These are tentative estimates, not measured effort; robust fleet security and recovery require further work.

## References

- [Existing network bridge proposal](../../../../src/services/network-bridge/README.md)
- [Deployment architecture](deployment.md)
- [Resource architecture](resources.md)
- [TLS 1.3, RFC 8446](https://www.rfc-editor.org/rfc/rfc8446.html)
- [DTLS 1.3, RFC 9147](https://www.rfc-editor.org/rfc/rfc9147.html)
- [RaptorQ, RFC 6330](https://www.rfc-editor.org/rfc/rfc6330.html)
- [Semtech LoRaWAN overview](https://www.semtech.com/lora/lorawan-standard)
- [LoRaWAN L2 1.0.4 specification](https://lora-alliance.org/wp-content/uploads/2021/11/LoRaWAN-Link-Layer-Specification-v1.0.4.pdf)
