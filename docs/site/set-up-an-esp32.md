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
Use a 2.4 GHz Wi-Fi network. Enrollment automatically installs the pinned build
tools for an original ESP32 with 4 or 8 MiB flash, including repairing incomplete
tool installations. The first run needs internet access and can take several
minutes. To install them ahead of time from the SDK checkout:

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

Mistyped network selections, invalid network names and invalid password lengths
can be corrected at the prompt. Network-name and password spaces are preserved.
For unattended entry, use `--ssid NAME --password-file PATH`, or `--open-network`
for a network without a password. An empty password file is rejected. Keep
password files outside the project and out of source control.

Success reports the device ID and an authenticated connection to that board and
base through the console. Keep the private enrollment/session directory printed
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

## 03 · Select the application {#select-the-application}

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
If you
removed any of the starter services, enrollment leaves your service selection to you and
prints the expected unit path. Review `board.profile` and application pins before
adding hardware services; enrollment cannot identify peripherals. For a Feather V2
with peripheral wiring, use `adafruit_feather_esp32_v2` and `flash_mb = 8`.

```sh
./micros compose -d HARDWARE_ID
./micros deploy -d HARDWARE_ID --dry-run
./micros deploy -d HARDWARE_ID
./micros logs -d HARDWARE_ID --follow
```

The status display logs simulated temperature, humidity and fan state once per second. Ctrl-C stops
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
