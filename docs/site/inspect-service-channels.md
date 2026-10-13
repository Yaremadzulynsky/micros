---
title: Inspect service channels
hide:
  - toc
---

<span class="docs-editorial"></span>

Use · Service channels
{: .arch-eyebrow}

# Inspect service channels

Read published protobuf messages through a declared bridge subscription. The
management console shows board status, resources, logs and activity; it does not
render service-defined plots or forms. Use [typed service commands](service-commands.md)
for request/reply operations.

## 01 · Discover a published port {#discover-a-published-port}

Server-backed deployment registers release metadata automatically. On a supporting
ESP32 base, after deploying the [pin-monitor application](../../services/pin-monitor/README.md)
with its bridge, open `./micros shell -d NAME`:

```text
ports
read board.pin-monitor samples
follow board.pin-monitor samples --seconds 15
```

These commands use pin-monitor as an example; it is not installed by enrollment.
For another application, use the actual service and port returned by `ports`. The package contains the
published port's schema and its matching bridge subscription. No presentation
metadata is required. Discovery comes from the exact confirmed release, not a
local recipe or a stale observation.

## 02 · Capture bounded evidence {#capture-bounded-evidence}

From the SDK checkout, with operator access already configured:

```sh
build/python/bin/python -m micros_tooling.diagnostics.collect \
  --device NAME --service board.pin-monitor --port samples \
  --seconds 15 --output build/capture.jsonl
```

Captures include device/base/graph identity, decoded messages, explicit gaps and
an end record. Readers share one device drain with separate cursors. A boot or
application change ends the capture. Lost samples and read errors must remain in
any interpretation; a published message alone does not prove a physical effect.

## 03 · Current boundary {#current-boundary}

Remote capture currently requires an ESP32 base advertising `ipc_stream: 1`, a
running publisher and bridge, and a registered release containing channel metadata.
Other targets do not yet implement this management adapter. This is a current
implementation gap, not the intended cross-platform feature contract.

Older releases missing channel metadata need rebuilding and deployment through
the server. Resolve any reported metadata-registration failure before discovery. Custom service-view metadata and endpoints are no longer supported.
See [Connect services](connect-service-ports.md) for channel ownership and bindings.
