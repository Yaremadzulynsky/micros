# Reference service implementations

These services demonstrate SDK usage and supply real consumers for regression
tests. They are application code, built separately from the resident framework.
Some deliberately use board-specific registers, pins or application behavior;
inspect their requirements before adapting them.

| Directory | Demonstrates |
| --- | --- |
| `button/`, `colors/`, `logger/` | GPIO input, typed messages, LED output and delivery timing |
| `dht/` | Feather ESP32 DHT11 acquisition and environmental messages |
| `coordination-controller/`, `coordination-console/`, `ir-coordination/` | Typed coordination endpoints and physical IR completion |
| `ir-capture/`, `ir-console/` | ESP32 IR transceiver and command/result channels |

The [MKR IPC example](../mkr-ipc/micros.toml) uses button and logger. Regression
recipes under [`tests/fixtures/`](../../tests/README.md) also consume these sources:
`configuration/`, `composition/`, and `ir/`. A service either declares its contract
in `service.toml` or receives its full declaration from the consuming recipe.
Generated bindings belong in ignored `generated/` directories.

Reusable diagnostic packages live in [`services/`](../../services/README.md).
The fixed IR loopback test lives in [`tests/fixtures/ir-selftest/`](../../tests/fixtures/ir-selftest/README.md).
New application-owned services belong in the project created by `micros new`.
