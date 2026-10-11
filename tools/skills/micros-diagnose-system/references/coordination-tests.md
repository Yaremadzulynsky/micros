# Set up coordination for a diagnostic test

Use this when a functional test needs typed state/action/event transport between
services on different devices. Read the [coordination contract](../../../../docs/site/coordination-reference.md)
and [current CLI](../../../../src/micros_tooling/fleet/coordination.py). Local bindings and
ordinary bridge channels do not need these server routes.

## Inspect and prepare

1. Read the live roster, endpoint status and current route status. Save the starting
   device/base/graph/activation identities and route evidence in the investigation.

   ```sh
   build/python/bin/python -m micros_tooling.fleet.coordination status
   ```

2. Identify the actual publisher and subscriber by device, service and typed port.
   Match direction, kind, schema, interface version and payload bound. Verify their
   authored recipes against deployed releases; the compiler does not reconstruct
   those contracts from archived applications. Both endpoints must be online and
   compatible. An offline controller needs an available compatible substitute
   within scope or a prepared trigger capability, not merely a route to it.
3. Determine how one fresh stimulus will be generated and observed. Inspect the
   publisher's pending/retained intent and completion history before connecting it;
   admission may forward existing intent immediately. A startup-only producer
   does not submit again because a route appears. Do not restart another device
   or bypass the action ledger to force a fresh request without that scope.
4. Prepare a complete route configuration including unrelated existing connections.
   Use a new investigation file instead of blindly applying a root demo file;
   unit paths are relative to that file. Use `drop_first = 0` for newly created
   normal test routes, rather than copying demonstration fault injection. Preserve
   existing route settings.

`apply` **replaces the whole route set** and reinitializes router bindings; it is
not additive. `status` gives names and binding evidence, not the complete endpoint
configuration needed for restoration. Obtain and save the authoritative definitions
(and the server's persisted `coordination.json` when needed and accessible) before
changing a nonempty set. Do not guess endpoints or post status output as configuration.
Account for all preserved routes' live admission requirements. Never drop an
unrelated route to get a test admitted. If preservation cannot be established,
resolve that specific configuration gap or choose a test with less shared impact.

## Create the missing route and exercise it

When the test and its effects are within existing authorization, perform setup
without asking again solely because the route is absent:

```sh
build/python/bin/python -m micros_tooling.fleet.coordination preview \
  --project build/INVESTIGATION/routes.toml
build/python/bin/python -m micros_tooling.fleet.coordination apply \
  --project build/INVESTIGATION/routes.toml
build/python/bin/python -m micros_tooling.fleet.coordination status
```

Review the complete preview and endpoint identities before apply. Verify the
required route is bound on both source and target with no blocked reason, within
a bounded setup deadline. A configuration response alone does not establish
endpoint admission. On rejection, inspect the mismatch/fencing instead of repeatedly
clearing, applying or restarting endpoints. A 404 is an access/server capability
issue; follow [access diagnosis](../../micros-device-access/references/capture-access.md).

Start observers, issue one fresh stimulus through the verified publisher interface,
and correlate delivery, execution and result with its current identity. If admission
already forwarded pending intent, determine its outcome before another request.
Retained success or merely seeing `bound` does not validate this test. Continue
into functional diagnosis after setup; do not end with “route created.”

## Finish and restore

Preserve the terminal or uncertain outcome and route/endpoint identities. Inspect
uncertain actions before further mutation; removing a route cannot undo a physical
effect. Restore the saved complete route configuration after a temporary test,
unless keeping the connection is the requested repair. `clear` removes every route
and is not per-test cleanup.

Restoration must respect current endpoint lifetimes. Application restarts fence
routes, and action re-admission after a one-sided lifetime change can be rejected.
Do not blindly replay a saved configuration or restart peers to make it pass.
Follow the contract's recovery rules within scope, verify the final routes and
applications, and report any remaining recovery need.
