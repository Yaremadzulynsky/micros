# Wi-Fi setup over USB

Plug in the ESP and run:

```sh
./micros wifi setup
```

The CLI finds a single ESP USB adapter, scans nearby networks, prompts for a selection and reads the password without echoing it. Choose `0` to enter a hidden network manually. It tests association and DHCP, saves the settings on the device, and updates the selected local device's IP for `./micros deploy`. Passwords are never command-line arguments or included in status responses.

```sh
./micros wifi status                 # Works even when Wi-Fi is unavailable
./micros wifi scan
./micros wifi setup --ssid "My network"
./micros wifi setup -d feather --port /dev/cu.usbserial-564E0535011
```

When several boards are connected, specify `--port`. An existing profile's saved MAC must match the USB device. Wi-Fi setup also works before a local device profile exists, but automatically updating the deploy address requires a saved profile. The USB adapter on this Feather can reset the board when opened; setup and status may briefly restart local services. `wifi status` waits up to ten seconds for that reconnection before reporting the resulting state.

A scan returns up to twelve networks and may briefly disconnect Wi-Fi. Application services continue running during network scans and connection tests. The CLI displays SSIDs safely, escaping control characters. Status distinguishes an unconfigured device, association in progress, waiting for an IP and a connected device, and includes the most recent disconnect reason. Authentication failures can reflect access-point policy as well as an incorrect password.

## Remembered settings and failure handling

The base reads an explicitly versioned credential record from the private `micros_wifi` NVS namespace. It saves a replacement only after the proposed network supplies an IP address. Failed connection tests expire after 45 seconds and restore the previous settings. Ctrl-C requests immediate cancellation; if the host disappears, the device's own deadline still applies. A power loss before saving leaves the prior NVS record in place. On reboot, the device connects using the saved settings without a computer.

These settings are independent of service packages and activation banks. Service deployments and rollbacks do not change Wi-Fi settings. The current development flash configuration does not encrypt NVS, so physical flash backups contain the saved Wi-Fi password and must remain private.

For automation, use a private password file rather than a shell argument:

```sh
./micros wifi setup --ssid "My network" --password-file /path/to/private/password --json
```

The file contains only the password, optionally followed by one newline. Leading/trailing spaces in the password are preserved. `--open-network` explicitly selects a network without a password. Interactive password entry refuses to fall back to visible input. JSON setup requires explicit network and password-file/open-network options to keep stdout machine-readable.

## Initial base update

USB provisioning requires the updated network-enabled base. Older firmware responds with an instruction to flash the new base. Generate or retain the management certificate/token with `micros_tooling/deployment/provision.py`, build with `micros_tooling/platforms/esp32/build_network.py`, and physically flash following [BUILDING.md](BUILDING.md). Wi-Fi values no longer belong in `sdkconfig`; the builder does not consume `build/private/sdkconfig.wifi`.

After flashing, run `./micros wifi setup` once. The HTTPS certificate/key/token are still provisioned separately and remain embedded in the private base image. Changing Wi-Fi afterward requires no rebuild or flash.

A base update can move the fixed native service slots. Rebuild service packages against the new ELF, install them through the physical controller, and pair the local deployment profile with that ELF before returning to OTA. Preserve the old ELF/packages separately: rollback packages from a different base cannot safely execute on the new base.

## Verification on the Feather

On 2026-09-06, the physical board passed USB provisioning, a network scan, reconnection from NVS after reboot, automatic restoration after an unavailable-network trial, and reboot during an unfinished trial. The interactive CLI was exercised in a real terminal: network selection worked, terminal echo was disabled during password entry, and the password was absent from captured output. The OTA deploy/rollback/no-op sequence passed afterward with all four services restored.

Evidence is under `build/wifi-hardware/`. A complete pre-change 8 MiB flash backup is retained privately under `build/backups/pre-wifi-setup/`. The final base retains about 4 KiB of free static IRAM. Host validation passed all 23 CTest checks. The focused Wi-Fi checks also passed with all 11 USB CLI cases, including the final status-reconnection behavior.
