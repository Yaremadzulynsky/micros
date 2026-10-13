# SW38 button color control over OTA

Press and release the Feather V2 user button to advance the onboard NeoPixel through **red, green, blue, yellow, cyan, magenta, white, off**. It starts with the configured `initial_color` after activation or reboot (schema default red). Holding the button advances once. The button service samples every 20 ms, debounces for 40 ms and publishes stable state transitions. Colors performs no debounce; it advances only on a confirmed released-to-pressed edge. A button held at startup must be released before the first press is counted. Brightness defaults to 1/255 per active channel; brightness and initial color are configured in `micros.toml`.

The [host regression recipe](../../../tests/fixtures/configuration/micros.toml) supplies the service declarations and board resources. Slots follow enabled-service declaration order. The service ABI is declared in `src/sdk/abi/`. Color selection is RAM state, not persisted across reboot.

## Board driver scope

Adafruit's [Feather V2 pinout](https://learn.adafruit.com/adafruit-esp32-feather-v2/pinouts) identifies GPIO38 as the pulled-up user button, GPIO0 as NeoPixel data and GPIO2 as NeoPixel/STEMMA power. The existing button publisher uses its admitted GPIO handle; the color service subscribes to its protobuf messages.

The base has no NeoPixel waveform primitive. The driver acquires the generated
`neopixel_data` and `neopixel_power` GPIO grants; generic handle ownership prevents
another managed service from acquiring those pins concurrently. The base configures
mux/direction from the deployed board map. Power uses the GPIO API, while the trusted
driver writes the granted data pin's atomic output registers for waveform timing.
This remains ESP32-specific native code, not a hardware sandbox.

On cooperative stop, the driver sends black and closes both GPIO handles; the BSP
performs GPIO cleanup. It does not save and restore arbitrary prior pin-register
state. The subscription is closed normally. There are no dynamic allocations,
background tasks or retained callbacks.

Timing is tied to the already-flashed **160 MHz, dynamic-scaling-disabled** V1 base. The builder checks that SDK configuration and links against its existing ELF. The 24-bit GRB waveform uses the CPU cycle counter in the reserved IRAM service slot, with core-local interrupts masked for approximately 30 microseconds. Interrupt state is restored before the 300-microsecond reset/latch interval. This is intended for one onboard pixel and occasional button changes, not a strip driver or hard-real-time timing guarantee. Software logs report requested colors; they cannot optically verify the pixel output.

Register addresses and fields are taken from the pinned ESP-IDF v5.5.2 ESP32 `soc/reg_base.h`, `soc/gpio_reg.h` and `soc/io_mux_reg.h`. WS2812 timing follows the 800 kbit/s protocol described in Adafruit's NeoPixel implementation: 0.4/0.8 microseconds high and 1.25 microseconds per bit, with a conservative 300-microsecond reset.

## Build and deploy

The root `micros.toml` builds its enabled services against the saved device's paired base firmware.

```sh
./micros build
./micros deploy --dry-run
./micros deploy
./micros logs
```

The builder only compiles independent services and packages. It records and checks the unchanged base binary digest. Deployment uses authenticated TLS to stage the inactive service bank and confirm the complete graph through the existing health/rollback mechanism. There is no base build, serial transfer or physical flash in this workflow.

Run `ctest --test-dir build/host-sanitize -R button_color_cycle --output-on-failure` after configuring/building the `color-cycle-tests` target. The focused sanitizer test covers bounce, holding, release/repress, eight-color wraparound and a held-at-boot button. Watch `./micros logs` for `NEOPIXEL color=...` after presses.

## Source layout

- `src/service.c`: subscribe and open the pixel; show the initial color; read a press, select the next color and display it; release resources on stop.
- `src/color_service.h`: private service state and stack budget.
- `src/button_input.c/.h`: subscription, protobuf validation, sequence continuity and press-edge detection. Reports presses without changing the palette.
- `src/palette.c/.h`: color values, selection, cycling and display diagnostics.
- `drivers/neopixel.c/.h`: board pin ownership and pixel waveform output.

Colors treats its first received state, or the next state after message loss, as a baseline. It does not infer a press from a sequence increment alone. New stream subscriptions read retained history. Colors suppresses actions confirmed at or before subscription time while still learning the retained baseline. A publisher restart changes its epoch and establishes a fresh baseline; subsequent live press edges work normally. A pressed baseline itself produces no action.
