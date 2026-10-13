---
description: Prepare a compatible ESP32 base update, distinguish first installation
  from OTA, and restore application readiness afterward.
hide:
- toc
---

<span class="docs-editorial"></span>

Operate · Update the resident base
{: .arch-eyebrow}

# Update the resident base

Change the base when the kernel, platform integration, or resident management
needs to change. Application services have their own [deployment path](deploy-an-application.md).
This procedure covers the optional **ESP32 A/B base-OTA profile**.
{: .arch-intro}

<nav class="docs-section-index" aria-label="On this page"><a href="#check-the-installed-boundary"><span>01</span> Check the installed boundary</a><a href="#prepare-the-matching-firmware"><span>02</span> Prepare the matching firmware</a><a href="#review-and-apply-an-ota-update"><span>03</span> Review and apply an OTA update</a><a href="#confirm-the-base-then-restore-the-application"><span>04</span> Confirm the base, then restore the application</a><a href="#restore-services-through-direct-management"><span>05</span> Restore services through direct management</a></nav>

## 01 · Check the installed boundary {#check-the-installed-boundary}

Inspect `./micros status -d NAME`. An OTA-capable base reports `base_ota`, including
its running slot, capacity, and trial state. The target firmware must fit the
installed layout and preserve the management identity and connection needed to
reach the candidate after reboot.

The layout has two base partitions and one shared application store. Switching
the base does not create or restore an application snapshot. Changing the
partition table or bootloader requires physical installation.

## 02 · Prepare the matching firmware {#prepare-the-matching-firmware}

Install the [ESP32 toolchain](set-up-an-esp32.md#prepare)
and activate it in the terminal used for this lower-level build:

```sh
source build/toolchains/esp-idf-v5.5.2/export.sh
build/python/bin/python src/micros_tooling/platforms/esp32/build_network.py \
  --ota --project UNIT.toml --board BOARD.toml --build build/base-review \
  --credentials EXISTING_PRIVATE_IDENTITY
```

Use the device's existing identity directory. For a relay-enabled base, also
pass `--relay-credentials ENROLLMENT_DIRECTORY` using its existing private enrollment. `UNIT.toml` and
`BOARD.toml` must describe the intended device. Keep the resulting ELF, matching
BIN, and `sdkconfig` together and private.

If the board does not yet have this OTA layout, back up its flash and use the
build directory's generated `flash_args` with the IDF flashing workflow. The
bootloader, partition table, initial OTA metadata, and base must be installed
together. Existing service storage can move; plan to redeploy matching services
afterward. A remote base update cannot perform this first layout migration.

## 03 · Review and apply an OTA update {#review-and-apply-an-ota-update}

For server-backed deployment, publish the target base so later service builds can
retrieve the exact ELF:

```sh
./micros server publish-base --firmware build/base-review/micros_runtime.elf
```

Then review and apply the update to the intended device:

```sh
./micros base-update -d NAME --firmware build/base-review/micros_runtime.elf --dry-run
./micros base-update -d NAME --firmware build/base-review/micros_runtime.elf
./micros status -d NAME
```

Preflight checks OTA support, capacity, flash size, and the ELF/BIN identity. The
BIN defaults to the ELF's sibling. Transfer writes the inactive base; only a
validated image becomes a boot candidate. The device then reboots, interrupting
management until the candidate reconnects.

## 04 · Confirm the base, then restore the application {#confirm-the-base-then-restore-the-application}

The candidate starts management with application execution stopped. The client
checks its identity and confirms it after at least five seconds of uptime. An
unconfirmed candidate has a 180-second trial timeout; reset before confirmation
uses the bootloader's rollback path.

Check that status reports the intended base with no pending trial. For a
server-backed device, [deploy its unit](deploy-an-application.md); the build
retrieves the matching published base.

## 05 · Restore services through direct management {#restore-services-through-direct-management}

The current base-update command does not replace an existing direct profile's
saved ELF. Keep that profile and its recovery history. Save the new base under a
new local name, using the existing credentials and current device address:

```sh
./micros device add NEW_NAME --host DEVICE_IP \
  --certificate .micros/devices/NAME/certificate.pem \
  --token-file .micros/devices/NAME/token \
  --firmware build/base-review/micros_runtime.elf \
  --sdkconfig build/base-review/sdkconfig --board BOARD.toml
./micros doctor -d NEW_NAME
```

Replace `NAME` with the original profile and `NEW_NAME` with an unused local name.
Confirm that the doctor's authenticated status and base compatibility checks pass.
Then build explicitly against the new ELF and deploy that compiled release:

```sh
./micros build --project UNIT.toml --firmware build/base-review/micros_runtime.elf \
  --bundle build/base-application-review
./micros deploy -d NEW_NAME --release build/base-application-review --dry-run
./micros deploy -d NEW_NAME --release build/base-application-review
./micros status -d NEW_NAME
./micros logs -d NEW_NAME
```

Use a new bundle directory. This explicit ELF/bundle path also avoids assuming
that a manually added profile has acquired the USB-paired hardware identity
required by ordinary source deployment. Verify the restored application's output.

If an acknowledgment is lost, resolve the outcome from status before restarting
the operation.

Source contract: [ESP32 update client](../../src/micros_tooling/deployment/base_ota.py)
and [resident update implementation](../../src/firmware/platforms/esp32/src/update.c).
