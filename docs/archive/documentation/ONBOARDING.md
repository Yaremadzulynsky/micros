# Set up or migrate an ESP32

Install CMake, Ninja and Git as described in [BUILDING](BUILDING.md), then run
`./micros setup --esp32` to install Python dependencies and the pinned ESP32 SDK.
Onboarding activates that SDK automatically. For the configured management server,
first complete [server setup and enrollment](../../../src/server/README.md), then use the
private enrollment directory for this board. Set `[management.server].url` to an
empty string to prepare a direct-network base without the server agent.

Inspect the workflow:

```sh
./micros init feather
./micros init feather --phase prepare --board boards/feather.toml \
  --relay-credentials .micros/server/enrollments/DEVICE_ID
./micros init feather --phase flash --port PORT
./micros init feather --phase connect --port PORT
./micros deploy -d feather
./micros doctor -d feather
```

Each phase is explicit and repeatable. `prepare` only builds locally, including
application admission. `flash` requires an explicit physical port, checks its MAC,
saves the entire detected 4 or 8 MiB flash before the first write, then flashes the prepared base.
`connect` uses existing Wi-Fi when connected or prompts for USB Wi-Fi setup,
resumes the physical controller and verifies authenticated base identity before
saving the profile. Pass `--transport docker` to connect when this host needs it.
The final `deploy` installs and confirms the initial application.

Private artifacts and phase receipts live in `.micros/onboarding/NAME/`. Failed
commands leave `last-command.log`; fix the reported issue and repeat that phase.
Opening USB may reset the board. `connect` allows up to 90 seconds for saved
Wi-Fi/DHCP before asking for credentials. Select the actual board definition;
`boards/feather.toml` describes the 8 MiB Feather and
`boards/esp32-no-controls.toml` is intended for the detected 4 MiB ESP32 without
onboard controls. Check its actual GPIO entries against the physical wiring before
preparing: a profile name does not establish hardware availability. An application's
resource requests must fit the selected map. Use the GPIO-free hello example for a
board without connected controls.

A new profile gets a distinct management identity. To preserve an existing one,
pass `--credentials PATH` during prepare, with its certificate, key and token.
On migration, the previous profile and its history are archived beside the flash
backup. Old releases remain associated with their original base. Restoring the
old base is a physical full-flash restore, not service rollback.

Current bases report ABI 0 revision 6 and graph format 3. The client also retains
graph-format-2 support for compatible identity-reporting ABI-5 bases with their
fixed board mapping; remote wiring changes require migration to format 3. A wrong
ABI or unidentifiable base is rejected before STOP. `doctor` separates connectivity
from compatibility failures.

For noninteractive Wi-Fi setup, `connect` accepts `--ssid` with `--password-file`
or `--open-network`. Passwords never belong in shell arguments or tracked TOML.

## Board selection and wiring

Keep the application in `micros.toml` and hardware definitions in `boards/NAME.toml`.
Start with `micros init NAME --phase prepare --board boards/NAME.toml`. Preparation
copies that board definition, generates the base GPIO mapping and validates the
application against it. Flash/connect preserve the exact reviewed definition in
the device profile. Normal `build -d NAME` and `deploy -d NAME` reuse it.

Graph-format-3 bases accept GPIO mappings and recovery-input selection with service
deployments. Select an editable file with `./micros device board NAME --board PATH`,
then deploy normally; rollback restores the previous wiring with its services.
Older bases tie mappings to the base fingerprint and need one physical migration.
Changing the chip, flash layout or base code still requires prepare/flash/connect.
No Python or board C edits are required for supported resource names, pins or directions.

For an isolated review, `micros_tooling/platforms/esp32/build_network.py --board boards/NAME.toml
--build DIRECTORY` passes the hardware definition into CMake. Direct IDF builds
accept `-D MICROS_BOARD_FILE=/absolute/path/board.toml`; the sole file in `boards/`
is the default if unambiguous. CMake regenerates the header when that file changes.
See [configuration](CONFIGURATION.md) for current processor, flash and memory limits.

`board.flash_mb` selects the generated partition layout and SDK flash setting.
Before flashing, onboarding probes the actual flash capacity and rejects a mismatch;
it backs up the full detected 4 MiB or 8 MiB before any flash write. A board with
`recovery_button = ""` skips boot-button handling and retains USB recovery.

## Saved networks and recovery hotspot

The resident Wi-Fi controller supports four primary networks in insertion order and
one optional fallback. On boot or connection loss it scans for each saved SSID
before attempting association. Unavailable networks are skipped; an available
network has at most 45 seconds to complete association and DHCP. After all primary
networks are absent or fail, the controller scans for the fallback. If none works,
it waits 10 seconds before starting another scan cycle. A working connection is
kept, including a working fallback; it does not continuously roam back to a primary.
These checks establish Wi-Fi/IP connectivity, not Internet or captive-portal access.

A base firmware update over USB is required to add this feature. Existing single-network
credentials become the first primary. Later list edits only write private NVS settings:
no firmware rebuild, relay change, or service deployment is needed. Passwords are not
returned by the list command and do not belong in tracked TOML files.

```sh
# Save networks even when they are not nearby; password prompts are hidden.
./micros wifi add -d feather --ssid "Home Wi-Fi"
./micros wifi add -d feather --ssid "Office Wi-Fi"
./micros wifi add -d feather --ssid "My iPhone" --fallback
./micros wifi list -d feather
./micros wifi forget -d feather --ssid "Office Wi-Fi"
```

All these commands use USB (`--port PORT` is also supported). `add` updates an
existing primary without changing its priority; new primaries append. `--fallback`
replaces the single fallback and removes that SSID from the primary list if needed.
For automation, pass `--password-file /private/path/password`; open networks require
`--open-network`. Saving credentials does not prove they are correct: turn on the
hotspot and verify recovery before relying on it. The hotspot must be visible and
compatible with the board's 2.4 GHz Wi-Fi radio.

`wifi setup` retains its connect-and-verify workflow, now checking availability first
and saving successful credentials into the list. `wifi add` is the way to provision
an out-of-range network. Forgetting the active network disconnects it and starts
selection again. Removing every entry leaves Wi-Fi unconfigured, including after reboot.
