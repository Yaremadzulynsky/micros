# SDK examples

Examples demonstrate reusable SDK features without selecting a personal device:

- [Clock and button tutorials](tutorials/toggle/README.md): two producers, one shared LED service and typed protobuf stream. Follow [Learn the micros way](https://docs.meetmicros.com/tutorials) alongside the source.
- `hello-service/`, `blink-service/`, `cpp-service/`: basic service lifecycles.
- `mkr-demo/`, `mkr-ipc/`, `esp8266-demo/`: platform demonstrations.
- `diagnostics/`, `pin-monitor/`, `network-bridge/`: explicit diagnostic and channel-access recipes.
- [services/](services/README.md): reference service implementations shared by examples and regression recipes.

These are source examples, not active board configurations. Actual units and
appliance-specific commands/recordings belong to application repositories.
Anonymous composition scenarios are available in
[`tests/fixtures/composition/`](../tests/fixtures/composition/README.md).

Start an independent application with `./micros new ../my-application`.
The generated project starts with three simulated climate services and two typed
channels, with no external hardware required. Use
`./micros scaffold-service services/my-service --new` from that project to add a
service. Follow the
[service walkthrough](../docs/site/write-a-service.md) before hardware-dependent examples.
See [repository map](https://docs.meetmicros.com/site/contributing/#repository-map).

- [Shell service](shell-service/README.md): raw protobuf commands and published status, inspectable through shell channel reads.
