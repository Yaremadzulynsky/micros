# Logger service

`board.logger` subscribes to `button.state`, validates decoded sequence ordering and reports confirmation-to-read latency as `LATENCY_US=...` through the runtime's diagnostic interface. Queue overruns produce a messages-missed diagnostic. Publisher epochs allow sequence resets after restart; sequence regression within an epoch and non-increasing timestamps remain invalid.

`src/service.c` implements its own native lifecycle descriptor. It shares the [ButtonState contract](../../../src/sdk/protos/button/v1/button_state.proto) and its generated typed read interface; it owns no GPIO or timer.

The consuming recipe declares its subscription; see the [MKR IPC example](../../mkr-ipc/micros.toml). Slots follow enabled-service declaration order. Pass the selected recipe explicitly with `--project PATH` when building or deploying it, and view diagnostics with `./micros logs -d NAME_OR_ID`.
