# Reusable service packages

These independently deployed services provide diagnostics and channel access.
They use the public SDK; they are not part of the resident firmware. The consuming
application selects each package and supplies its settings, resources and wiring.

| Package | Purpose |
| --- | --- |
| [diagnostics/](diagnostics/README.md) | Channel probe, triggered signal recorder and controlled replay |
| [network-bridge/](network-bridge/README.md) | Management access to explicitly declared channel ports |
| [pin-monitor/](pin-monitor/README.md) | Timestamped digital and analog pin observation |

Each package has a `service.toml`; runnable integration recipes are under
[`examples/`](../examples/README.md). Consult the package contract for supported
resources and targets; placement here does not imply support on every board.

Reference applications belong in [`examples/services/`](../examples/services/README.md),
test-only code in `tests/fixtures/`, and resident management in
`src/firmware/controller/`. Developer-owned services stay in the consuming
application repository. See [repository map](https://docs.meetmicros.com/site/contributing/#repository-map).
