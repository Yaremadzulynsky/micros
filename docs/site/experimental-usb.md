---
title: "Advanced: standalone USB setup"
---

# Advanced: standalone USB setup

Use this optional workflow to install and deploy to an ESP8266 with **4 MiB flash**
or **Arduino MKR WiFi 1010** without a management server. You manually prepare,
flash and pair the runtime, then create a board unit for direct USB deployment.

**For normal setup, follow [Enrollment help](set-up-an-esp32.md) and run
`./micros enroll`.** Enrollment supports both boards, configures their server
connection and installs the climate starter. You do not need the manual commands
on this page before enrolling.

The experimental support status belongs to the platform ports, not to the choice
of USB or server deployment. Review their
[prerequisites and limits](set-up-an-esp32.md#target-prerequisites).

## Prepare host tools and identify the board

Run SDK commands below from the checkout installed by [Quickstart](get-started.md).
Install the [target prerequisites](set-up-an-esp32.md#target-prerequisites) first.
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

## Create the application and board unit

From the directory where you keep applications, use the SDK on PATH:

```sh
micros new my-application
cd my-application
```

The new project contains the three simulated climate services and `units/host.toml`.
Because this standalone workflow skips enrollment, you must create its board unit
manually. Copy `units/host.toml` to `units/HARDWARE_ID.toml`, retain all three services
and both channels, and add the following `[unit]` and `[board]` sections:

```toml
[unit]
device_id = "HARDWARE_ID"

[board]
profile = "arduino_mkr_wifi_1010" # Use esp8266_4mb for ESP8266.
```

Use the observed twelve-digit hardware ID. Set each service's `memory.stack_bytes`
to 1024 on MKR or 1536 on ESP8266. Size stacks for changed behavior and inspect
runtime headroom. There is no external sensor, fan or display to wire.

From the application directory, with `MICROS_SDK` still exported:

```sh
./micros compose -d HARDWARE_ID
./micros deploy -d HARDWARE_ID --via usb --port PORT --dry-run
./micros deploy -d HARDWARE_ID --via usb --port PORT
./micros status -d HARDWARE_ID --via usb --port PORT
./micros logs -d HARDWARE_ID --via usb --port PORT
```

Expect all three services running, no pending trial, and `Simulated climate`
lines with fan ON/OFF transitions. A successful upload alone is not successful activation. If activation
fails, inspect status and logs before another write. USB serial opening may
reset ESP8266, so compare observations within the same boot when testing timing.
For network enrollment, return to [Enrollment help](set-up-an-esp32.md).
