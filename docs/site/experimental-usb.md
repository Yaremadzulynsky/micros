---
title: Experimental USB deployment
---

# Experimental USB deployment

ESP8266 with **4 MiB flash** and **Arduino MKR WiFi 1010** have a local USB
path. It does not require a management server, Wi-Fi setup or new network
credentials. These are experimental targets, not ESP32 feature parity.
Run SDK commands below from the checkout installed by [Quickstart](get-started.md).

## Prepare host tools and identify the board

Both targets need the Python environment from `./micros setup`.
For ESP8266, install Python 3.10, CMake and Ninja on PATH. Apple Silicon also
needs Rosetta for the pinned Intel compiler. For MKR, install Arduino CLI and a
complete ARM GCC 10+ toolchain (`arm-none-eabi-gcc`, `g++`, `objcopy`) on PATH.
`init --phase prepare` downloads pinned platform dependencies; it does not flash.
MKR setup installs Arduino SAMD core 1.8.13 into Arduino's user data directory
if absent. Other downloaded dependencies stay in the SDK's `build/` directory.

```sh
./micros discover --port PORT --json
```

Replace `PORT` with the exact USB interface. Discovery may reset the board.
Record its `platform` and twelve-digit `device_id`; do not identify hardware by
its port name alone. A stock MKR sketch may not expose its NINA MAC until the
base is installed. Select only the physical board you intend to replace.

## Build and install the base

Choose one target:

```sh
./micros init HARDWARE_ID --platform esp8266 --phase prepare
./micros init HARDWARE_ID --platform esp8266 --phase flash --port PORT
```

```sh
./micros init HARDWARE_ID --platform samd21 --phase prepare --compiler-dir /path/to/arm-gcc/bin
./micros init HARDWARE_ID --platform samd21 --phase flash --port PORT --compiler-dir /path/to/arm-gcc/bin
```

**Flash replaces firmware and application banks.** It preserves existing network
settings, which can reconnect an already configured board to its previous server.
It does not create new credentials or enroll the board in a server. Keep the
SDK's `.micros/` state: pairing retains the exact ELF needed for service builds.
`--phase connect --firmware PATH/TO/EXACT.elf` pairs an already installed matching
base without flashing; a different ELF is rejected.

For an unidentified stock MKR, use a temporary local name for `init`, then read
`discover` after installation and pair with `--phase connect` using its hardware ID.

## Create a target-specific starter

From the directory where you keep applications, use the SDK on PATH:

```sh
micros new my-mkr-application --platform samd21
# Or, for ESP8266:
micros new my-esp8266-application --platform esp8266
```

These starters select `arduino_mkr_wifi_1010` or `esp8266_4mb` and omit the
ESP32-only `flash_mb` field. The MKR starter gives hello a 1024-byte worker stack;
the ESP8266 starter retains 4096 bytes. The default `micros new` remains ESP32.
The MKR's smaller RAM budget cannot reliably accommodate the ESP32 starter's
4096-byte hello worker together with management. Size stacks for each real
service and inspect runtime headroom.

In your application, rename `units/000000000000.toml` to
`units/HARDWARE_ID.toml` and set `unit.device_id` to that same ID. No hello source
or memory edits are needed for a target-specific starter.

If converting an existing ESP32 starter instead, replace its board section with
`profile = "arduino_mkr_wifi_1010"` or `profile = "esp8266_4mb"`, remove
`flash_mb`, and set hello's `memory.stack_bytes` to 1024 for MKR.

From the application directory, with `MICROS_SDK` still exported:

```sh
./micros compose -d HARDWARE_ID
./micros deploy -d HARDWARE_ID --via usb --port PORT --dry-run
./micros deploy -d HARDWARE_ID --via usb --port PORT
./micros status -d HARDWARE_ID --via usb --port PORT
./micros logs -d HARDWARE_ID --via usb --port PORT
```

Expect `example.hello` running, no pending trial, and repeated `Hello world`
lines. A successful upload alone is not successful activation. If activation
fails, inspect status and logs before another write. USB serial opening may
reset ESP8266, so compare observations within the same boot when testing timing.
For network enrollment, return to [Set up a board](set-up-an-esp32.md).
