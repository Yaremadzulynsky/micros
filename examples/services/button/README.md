# Button service

`board.button` reads the active-low `user_button` resource (GPIO38 on the Feather V2) every `sample_interval_ms` (default 20 ms). It confirms a state only after `debounce_ms` (default 40 ms) of unchanged input, then publishes the initial stable state and subsequent transitions to `button.state`. Holding the button produces no repeated messages.

The protobuf `ButtonState` payload contains:

- `pressed`: true means pressed; false means released.
- `sequence`: starts at 1 and advances once per published state, for ordering and loss detection.
- `monotonic_us`: time the debounced state was confirmed.
- `publisher_started_us`: nonzero monotonic start time identifying this publisher instance.
  A restart or sequence exhaustion begins a new epoch.

Subscribers establish a baseline from their first state, including a button held at boot. A released-to-pressed transition is a press action; a click gesture spanning press and release is not generated. After message loss, use the next state as a new baseline. A new stream subscription reads from the oldest retained state, so an idle publisher does not necessarily leave it waiting for a baseline. Colors uses retained states only as a baseline and acts only on transitions confirmed after its subscription opened. A changed publisher epoch establishes a new baseline without failing surviving consumers. A pressed first state or a press following message loss establishes a baseline rather than generating an action.

`src/service.c` shows hardware sampling, conditional publication and lifecycle cleanup. `src/button_state.h` owns configuration, state and debounce details. The shared `micros.button.v1.ButtonState` schema generates the C type and codec in `generated/`; `button_button_publish` serializes the typed message automatically. It replaces the old synthetic Sample contract; publisher and subscribers must be updated together.

The consuming recipe declares the `user_button` grant, one timer and a publishing channel. See the [MKR IPC example](../../mkr-ipc/micros.toml) or the [host regression recipe](../../../tests/fixtures/configuration/micros.toml). Pass the selected recipe explicitly with `--project PATH` when generating or building it. Slots follow enabled-service declaration order.

The button interface is minor 1. Publisher and consumer grants must use compatible versions; the service ABI is declared in `src/sdk/abi/`.
