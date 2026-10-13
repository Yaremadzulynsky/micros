---
title: Enrollment help
hide:
  - toc
---

<span class="docs-editorial"></span>

Use · Enrollment help
{: .arch-eyebrow}

# Enrollment help

Enroll a USB-connected board with a reachable management server. Enrollment
installs the Micros runtime, connects the board, and deploys the three-service
simulated climate starter. Use this same enrollment flow for original ESP32,
ESP8266 with 4 MiB flash, and Arduino MKR WiFi 1010. No sensor, fan or display
hardware is needed.
{: .arch-intro}

## Before enrollment {#prepare}

The [Quickstart](get-started.md) runs `./micros enroll`, which includes server
selection or creation. This page supplies prerequisites and recovery details;
you do not need a separate board-setup command. Choose an address the board can reach. A board cannot use the server computer's `localhost`.
Use a 2.4 GHz Wi-Fi network. The first run needs internet access to install pinned
platform dependencies and can take several minutes.

### Target prerequisites and limits {#target-prerequisites}

Run `./micros setup` in the SDK checkout for the shared tools, then check your target:

| Target | Build prerequisites |
| --- | --- |
| Original ESP32, 4 or 8 MiB flash | Enrollment installs the pinned ESP-IDF build tools and repairs incomplete installations. Optionally run `./micros setup --esp32` in the SDK checkout ahead of time. |
| ESP8266, 4 MiB flash | Python 3.10, CMake and Ninja on PATH; Rosetta on Apple Silicon for the pinned Intel compiler. Enrollment installs the pinned ESP8266 SDK, compiler and isolated Python dependencies. |
| Arduino MKR WiFi 1010 | Arduino CLI and a complete ARM GCC 10+ toolchain (`arm-none-eabi-gcc`, `g++`, `objcopy`) on PATH. Enrollment installs pinned core/library dependencies; Arduino's bundled GCC 7 is too old. |

ESP8266 and MKR are experimental ports: their RAM, flash and peripheral support
have different limits from ESP32. See the [ESP8266 platform limits](../../src/firmware/platforms/esp8266/README.md#flash-and-service-limits)
and [MKR platform notes](../../src/firmware/platforms/samd21/README.md).
They still use `./micros enroll` below. ESP32-S2/S3/C-series are not interchangeable
with original ESP32. For a private server certificate, check
[board certificate trust](run-management-server.md#board-certificate-trust) before enrollment.

## Enrollment prompts {#enroll-over-usb}

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

MKR enrollment also installs the selected server’s certificate bundle in NINA
and restores the Micros base automatically. Keep USB connected through both steps.
See [certificate trust](run-management-server.md#board-certificate-trust).

Mistyped network selections, invalid network names and invalid password lengths
can be corrected at the prompt. Network-name and password spaces are preserved.
For unattended entry, use `--ssid NAME --password-file PATH`, or `--open-network`
for a network without a password. An empty password file is rejected. Keep
password files outside the project and out of source control.

Success reports the device ID, an authenticated connection to that board and
base through the console, and confirmation of the starter deployment. Keep the private enrollment/session directory printed
by the tool; it contains credentials and exact build artifacts.

After a failed or canceled ESP enrollment, use the printed `Resume:` command to
keep the selected server and USB port. It omits Wi-Fi secrets and reuses working
saved network settings, or prompts privately if configuration is still needed.
For interruption, rerun enrollment. If a flash result is uncertain, the tool
checks saved images and may require `--retry-flash`; inspect its saved log before
requesting that retry. A board with a matching unfinished local enrollment remains selectable as
“resume unfinished enrollment,” even if it reached the console before the previous
command finished. Its installed firmware is retained. Confirmed enrollments use
the normal deployment/update flow.

If an **unfinished ESP8266 or MKR enrollment needs a firmware fix**, first select the
corrected SDK revision, then run `./micros enroll --rebuild-base`. This explicitly
builds and flashes a new base, archives the previous attempt, and retains the
enrollment credentials. If MKR firmware rejects bootloader entry, double-press its
Reset button before running the command. It is different from `--retry-flash`, which retries saved images.

## What enrollment installs {#select-the-application}

When enrollment succeeds inside a [starter project](get-started.md#create-your-project),
it creates `units/HARDWARE_ID.toml` with the detected identity, board profile and
ESP32 flash capacity, selecting the project's simulated climate services. There is no placeholder
unit in a new project. Each additional board gets its own file referencing the same
example. Existing units and service source are preserved. The command prints the
next deployment commands for your later edits. By default, enrollment also builds
and installs a pristine SDK copy of the simulated climate starter through the
server, and waits for all three services to confirm. This requires no external
hardware. Use `--no-starter` to leave only device management running.

The installed starter and deployment evidence are retained under `build/enrollment/`
in your application, or the enrollment session's `build/` directory when enrolling
outside a project. Application-owned edits are never run automatically during
enrollment. If starter installation fails, the board remains enrolled: inspect
status and use the printed deployment command, without erasing or re-enrolling.
If you removed any of the starter services, enrollment leaves your service selection to you and
prints the expected unit path. Review `board.profile` and application pins before
adding hardware services; enrollment cannot identify peripherals. For a Feather V2
with peripheral wiring, use `adafruit_feather_esp32_v2` and `flash_mb = 8`.

Inspect the application that enrollment already installed:

```sh
./micros status -d HARDWARE_ID
./micros logs -d HARDWARE_ID --follow
```

Expect three Running services: `example.climate-sensor`, `example.fan-controller`
and `example.status-display`, with no pending trial. For later source or setting
changes, [preview and deploy the selected unit](deploy-an-application.md).

The status display logs simulated temperature, humidity and fan state once per second. Ctrl-C stops
following logs without stopping the board. See [deployment](deploy-an-application.md)
for updates and rollback.

## Change Wi-Fi or refresh a direct profile {#change-wi-fi-or-refresh-a-direct-profile}

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

## Advanced: standalone USB setup

If you deliberately want to work without a management server, see
[Advanced: standalone USB setup](experimental-usb.md) for MKR and ESP8266.
That route manually prepares, flashes and pairs a base, then creates the board
unit for direct USB deployment. It is optional; ordinary enrollment handles these
steps and creates the unit for you.
