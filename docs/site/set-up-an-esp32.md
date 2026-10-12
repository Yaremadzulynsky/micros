---
title: Set up a board
hide:
  - toc
---

<span class="docs-editorial"></span>

Start · Set up a board
{: .arch-eyebrow}

# Set up a board

Enroll a USB-connected board with your local management server, then select it
in your application's unit file. Enrollment installs a management base; it does
not deploy your application.
{: .arch-intro}

## 01 · Prepare {#prepare}

First [start the server and console](run-management-server.md) using an address
the board can reach. A board cannot use the server computer's `localhost`.
Use a 2.4 GHz Wi-Fi network. For an original ESP32 with 4 or 8 MiB flash, install
the tools from the SDK checkout:

```sh
./micros setup --esp32
```

The current wizard also has experimental ESP8266 4 MiB and Arduino MKR WiFi 1010
paths with different build prerequisites. For a first deployment without a server,
follow [experimental USB deployment](experimental-usb.md).
ESP32-S2/S3/C-series are not interchangeable with original ESP32.

## 02 · Enroll over USB {#enroll-over-usb}

**Enrollment replaces firmware and does not back up the existing flash.** Save
anything needed from the board first. USB identification can reset a controller.
The command proceeds with installation after controller selection; do not expect
a second installation confirmation.

```sh
./micros enroll
```

First choose a saved server, connect to an existing one using its operator bundle,
or create a server on this computer. The wizard shows the destination before any
authentication; Cloudflare Access is optional and depends on that server.
The selection is remembered privately for this project. See
[server profiles](run-management-server.md#server-profiles) to manage several servers
or select one explicitly with `--server NAME`.

Then choose the board, give it a name, and enter Wi-Fi credentials when prompted.
Password entry is hidden. With several boards attached, `--port PORT` selects
one explicitly. Enrollment detects the chip and hardware identity, not arbitrary
retail-board wiring or attached peripherals.

Success reports the device ID and an authenticated connection to that board and
base through the console. Keep the private enrollment/session directory printed
by the tool; it contains credentials and exact build artifacts.

For interruption, rerun enrollment. If a flash result is uncertain, the tool
checks saved images and may require `--retry-flash`; inspect its saved log before
requesting that retry. Already enrolled controllers are rejected by this wizard;
use the normal deployment/update flow for those controllers.

If an **unfinished ESP8266 enrollment needs a firmware fix**, first select the
corrected SDK revision, then run `./micros enroll --rebuild-base`. This explicitly
builds and flashes a new base, archives the previous attempt, and retains the
enrollment token. It is different from `--retry-flash`, which retries saved images.

## 03 · Select the application {#select-the-application}

In your [project](get-started.md#create-your-project), replace the placeholder
unit ID and filename with the enrolled hardware ID. Set `board.profile` and
`board.flash_mb` for the physical board; enrollment does not infer application pins.
For a Feather V2, use `adafruit_feather_esp32_v2` and `8`.

```sh
./micros compose -d HARDWARE_ID
./micros deploy -d HARDWARE_ID --dry-run
./micros deploy -d HARDWARE_ID
./micros logs -d HARDWARE_ID --follow
```

Hello should produce a greeting approximately once per second. Ctrl-C stops
following logs without stopping the board. See [deployment](deploy-an-application.md)
for updates and rollback.

## 04 · Change Wi-Fi or refresh a direct profile {#change-wi-fi-or-refresh-a-direct-profile}

On ESP32 bases with saved-network support, use USB:

```sh
./micros wifi status --port PORT
./micros wifi scan --port PORT
./micros wifi add --port PORT --ssid "Workshop"
./micros wifi list --port PORT
```

`add` prompts privately for the password. Use `--fallback` for the optional recovery
network and `wifi forget --port PORT --ssid NAME` to remove one. Check `wifi status`
after changing it. Exact flags are in `./micros wifi add --help`.

For an existing **direct HTTPS profile** whose address changed:

```sh
./micros device refresh NAME --port PORT
./micros doctor -d NAME
```

Refresh verifies the board identity before changing the saved address. Direct
ESP32 setup via `init --phase …` remains available in the
[platform instructions](../../src/firmware/platforms/esp32/README.md).
Erasing a controller is a separate destructive operation; see [CLI](cli.md#erase-a-controller).
