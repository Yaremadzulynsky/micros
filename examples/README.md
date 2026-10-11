# SDK examples

Examples demonstrate reusable SDK features without selecting a personal device:

- `hello-service/`, `blink-service/`, `cpp-service/`: basic service lifecycles.
- `mkr-demo/`, `mkr-ipc/`, `esp8266-demo/`: platform demonstrations.
- `diagnostics/`, `pin-monitor/`, `network-bridge/`: explicit diagnostic and channel-access recipes.
- [services/](services/README.md): reference service implementations shared by examples and regression recipes.

These are source examples, not active board configurations. Actual units and
appliance-specific commands/recordings belong to application repositories.
Anonymous composition scenarios are available in
[`tests/fixtures/composition/`](../tests/fixtures/composition/README.md).

Start an independent application with `./micros new ../my-application`.
See [repository map](https://docs.meetmicros.com/site/contributing/#repository-map).

- [Shell service](shell-service/README.md): raw protobuf commands and published status, inspectable through shell channel reads.
