---
title: Coordination
hide:
  - toc
---

<span class="docs-editorial"></span>

Reference · Coordination
{: .arch-eyebrow}

# Coordination

Coordination connects typed ports across devices through the management server.
Ordinary local channels and console captures are separate mechanisms.
{: .arch-intro}

## 01 · Choose semantics {#choose-semantics}

| Kind | Use | Loss/restart boundary |
| --- | --- | --- |
| State | Current desired/observed value | New values replace older ones. |
| Action | Request work and receive an outcome | One pending request per publication; an interrupted outcome can remain unknown. |
| Event | Transient occurrence | Missed events are not recovered. |

Current interfaces declare `kind` under `[delivery]`. Coordination channels use
latest/depth 1 with payloads up to 64 bytes. State/action/event endpoints require
matching contracts. Current deployment composition supports up to eight connections
and one route per physical device/channel endpoint.

## 02 · Generate callbacks {#generate-callbacks}

Generation opens ports before application init, dispatches before step, and closes
ports after stop. Incoming ports and outgoing action results need their generated
callbacks. Outgoing operations are nonblocking; they never invoke callbacks
synchronously. Each dispatch delivers at most one callback per port in declaration
order. Callback message pointers are borrowed; copy values you retain.

The [IR controller](../../examples/services/coordination-controller/src/service.c) is an
implemented example. Use the generated header for operation and callback signatures.
Ordinary manually opened timers/GPIO still require their normal cleanup.

## 03 · Admit routes {#admit-routes}

The multi-board example uses the supported [composition workflow](configuration-reference.md):

```sh
./micros compose tests/fixtures/composition/deployments/ir.toml --output build/ir-review
```

This is offline and uses example identities. A connection selects endpoints:

```toml
[[connections]]
name = "ir.operation"
from = "controller.controller.operation"
to = "feather.ir.operations"
```

Adapt IDs, boards, services, and server settings, then deploy each emitted unit.
With both boards online, run from the SDK root using your server state directory:

```sh
build/python/bin/python -m micros_tooling.fleet.coordination preview --project build/ir-review/coordination.toml --server-state SERVER_STATE
build/python/bin/python -m micros_tooling.fleet.coordination apply --project build/ir-review/coordination.toml --server-state SERVER_STATE
build/python/bin/python -m micros_tooling.fleet.coordination status --project build/ir-review/coordination.toml --server-state SERVER_STATE
```

Unlike composition, preview contacts the server/endpoints. Apply admits routes
against their current boot, base, application, and activation identities.

## 04 · Disconnects and restarts {#disconnects-and-restarts}

A disconnected executor does not prove an action failed. The adapter invents no
timeout/retry policy. A second action while one is pending returns `MICROS_ERROR_STATE`.
Terminal notification occurs at most once in the publisher lifetime, clearing its
pending state before the callback.

A board restart, application stop, or replacement invalidates the relevant route;
re-admit current endpoints. Old cached intent is not injected into a replacement
application. Action bookkeeping is volatile across power loss: exactly-once physical
effects are not guaranteed. Inspect the outcome before repeating a physical action.

Source: [route client](../../src/micros_tooling/fleet/coordination.py),
[generated adapter](../../src/micros_tooling/config/coordination_codegen.py),
[coordination ABI](../../src/sdk/abi/include/micros/coordination.h).
