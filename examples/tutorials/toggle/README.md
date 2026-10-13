# Clock or button → toggle events → LED

Two applications on one board. Lesson 1 selects `clock` + `led`. Lesson 2
selects `button` + the exact same `led`. Both use `protos/toggle` and the
`toggle` stream. Do not select both producers together.

Follow [Blink an LED](https://docs.meetmicros.com/tutorials/blink), then
[Button-controlled LED](https://docs.meetmicros.com/tutorials/button). This directory
is the canonical source; the docs build publishes the lessons and download
directly from this repository.
Start with the [Quickstart](https://docs.meetmicros.com/site/get-started/) and
[board enrollment](https://docs.meetmicros.com/site/set-up-an-esp32/) if needed.
These GPIO tutorials are separate from the no-wiring climate starter.

## Use in an enrolled micros application

Use public micros revision `3601787b4fc49b38bc9e2942cd5feba3c4c0ac82` or later.
It fixes MKR/ESP8266 validation of generated no-pull pin bindings. Existing
applications keep the SDK revision pinned in their `micros.lock`.

Copy this bundle's `services/`, `protos/` and `tests/` into your application.
Also copy `clock-unit.toml` and `button-unit.toml` into the application root;
the composition tests read both fragments from there.
Keep its existing `micros` launcher, `micros.lock`, credentials and enrolled unit.
Run the commands below from that application root with the SDK selected by it.
A host C compiler is required for the tests.

1. Open `units/<hardware-id>.toml`. Keep the `[unit]` and `[board]` identity.
   Replace the starter services/channels with `clock-unit.toml`'s sections.
   These files are fragments, not complete identities or deployable boards.
2. Replace LED pin **13** with your verified GPIO output. Use a controllable
   onboard LED or an LED with a suitable series resistor. These examples write
   electrical 0/1; visible on/off depends on the actual LED wiring.
3. Generate the service APIs, run tests, inspect the board's pin map, compose,
   then preview and deploy to that explicit board:

   ```sh
   ./micros generate --service services/clock
   ./micros generate --service services/led
   ./micros test -v -k toggle
   ./micros pins -d HARDWARE_ID --all
   ./micros compose -d HARDWARE_ID
   ./micros deploy -d HARDWARE_ID --dry-run
   ./micros deploy -d HARDWARE_ID
   ```

   Substitute the real enrolled ID for `HARDWARE_ID`. Confirm several physical
   LED cycles: by default a toggle every 500 ms, one full cycle each second.
   Pin labels and header positions are not necessarily micros GPIO numbers.
4. For lesson 2, replace `[services.clock]` with `[services.button]` from
   `button-unit.toml`. Keep `[services.led]` and `[channels.toggle]` unchanged.
   Replace button pin **12** with a verified input. Connect a switch to GND
   and use a 10 kΩ external pull-up to the board's logic supply. The example
   requests no internal pull. Select a pin not reserved for boot, flash or
   management on your board.
5. Run `./micros generate --service services/button`, then repeat test,
   compose, dry-run and deploy. Each confirmed press must toggle once;
   holding and releasing must not toggle. A button held at startup emits
   one event after the debounce window. Membership changes can restart the
   whole graph; source reuse does not mean uninterrupted output state.

## What micros generates

`service.toml` declares named resources and a typed publication/subscription.
`interface.toml` selects stream delivery for the protobuf message.
`micros generate --service ...` writes hooks, bindings and protobuf codecs under
`build/services/<service>/generated/` (the command reports the exact output directory).
Edit the supplied C and TOML files, not generated files. Deploy regenerates and
compiles selected service code against the device's paired runtime base.

## Bounds and failure behavior

There are two services, one four-message stream and no application heap calls.
Each service requests 1,536 bytes of stack. Generated instance contexts and
resource handles are bounded; platform admission checks account for their
arenas, stack reservations and channel storage. This budget fits both example
packages on MKR, ESP8266 and ESP32 in the native build checks. It is not a
measurement of peak stack use on a physical board.

The clock interval is bounded to 100–2,000 ms. Button sampling is 1–10 ms
(default 5); debounce is 10–100 ms (default 30). Debounce measures stability
across samples, so it cannot detect transitions between samples.

Each event has a same-board monotonic timestamp. The LED ignores retained
events at or before its own start. It consumes individual stream events; a
latest-value channel would merge intermediate toggle actions. More than four
unread events can lose data: the loss callback fails the LED service, and its
stop hook writes 0. Restart the application to recover. Publishing successfully
means queued, not yet acted on by the LED.

## Verification scope

`./micros test -v -k toggle` compiles the actual three C services, generated
lifecycle/IPC code and nanopb codecs. A deterministic GPIO/timer/bus fixture
checks default and selected clock intervals, both producers against the same LED,
bounce, holds, releases, buffered events, overflow, retained-event restart
filtering, error propagation and resource cleanup. It also composes both unit
graphs for MKR WiFi 1010, ESP8266 4 MiB and ESP32 DevKitC profiles.

Host tests model the runtime interfaces; they do not run physical GPIO or the
entire firmware. Native cross-compilation checks package admission and linking,
not physical wiring, real scheduler timing or delivery over the management
server. Verify the physical behavior after deployment as described above.
