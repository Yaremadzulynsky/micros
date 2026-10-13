# Slim base-only OTA

The optional `CONFIG_MICROS_BASE_OTA` build updates the base through the existing
HTTPS or outbound relay connection. It has two firmware slots, one shared
application store, and no factory recovery image. The shell remains an add-on;
this change does not include a shell.

OTA writes only the inactive base partition. It neither snapshots nor rolls back
application packages. The existing two service staging banks occupy **256 KiB
combined**, shared by both bases. There are no per-base application banks.

## Flash and memory budget

Measured with ESP-IDF v5.5.2, flash-executed services, and HTTPS plus outbound relay,
on 2026-09-08. The 4 MiB comparison uses matching board, enrollment and settings;
the baseline disables base OTA. Sizes describe linked builds, not runtime heap peaks.

| Measurement | Without base OTA | With base OTA | Increase |
|---|---:|---:|---:|
| Firmware BIN | 908,384 B | 917,904 B | **9,520 B** |
| Static DRAM | 49,384 B | 49,568 B | **184 B** |
| IRAM | 94,319 B | 94,319 B | **0 B** |

The 8 MiB Feather OTA build also measures 917,904 bytes. Neither profile requires
PSRAM. A 4 KiB upload body uses the existing bounded management request path;
there is no full-image RAM buffer or additional OTA worker. ESP-IDF allocates an
OTA handle during transfer and a timer object during a trial. Measure peak heap
and latency on hardware before unattended deployment.

| Partition budget | 4 MiB boards | 8 MiB Feather |
|---|---:|---:|
| Each of two base slots | 1.5 MiB | 2 MiB |
| Shared service storage | 256 KiB | 256 KiB |
| Shared activation journal | 8 KiB | 8 KiB |
| Unallocated flash after all partitions | **632 KiB** | **3,704 KiB** |

The 4 MiB firmware slot has 654,960 bytes free (41.6%). NVS and PHY offsets stay
at `0x9000` and `0xf000`. OTA metadata occupies `0x10000..0x11fff`; base A starts
at `0x20000`. All application partitions are 64 KiB aligned. Generate the complete
layout with `board_partitions(board, ota=True)`; do not hand-edit firmware offsets.

## Build and initial installation

Activate the pinned ESP-IDF environment as described in [BUILDING](BUILDING.md).
Use the device's existing management credentials and relay enrollment when building
its replacement, so the same operator connection can reach the trial base:

```sh
build/python/bin/python micros_tooling/platforms/esp32/build_network.py \
  --ota --board boards/esp32-no-controls.toml --build build/ota-4mb \
  --credentials PATH/TO/EXISTING/PRIVATE/CREDENTIALS \
  --relay-credentials .micros/server/enrollments/DEVICE_ID
```

For the Feather, select `boards/feather.toml` and `build/ota-8mb`. A direct-only
build uses a project without a management server and omits relay enrollment.
The builder preserves OTA configuration on subsequent builds of the same directory.

The **first installation requires physical flashing** of the bootloader, partition
table, initial OTA metadata and base together. Use that build directory's generated
`flash_args`/IDF flash command. The old factory layout places the firmware at a
different offset and is incompatible. Service storage also moves: plan to deploy
fresh matching service packages after migration. This work built artifacts only;
no board was flashed or erased.

Treat firmware artifacts as private: they include the existing management identity.
An update changes only the app partition; bootloader, partition table and physical
flash size must continue to match the installed OTA layout. OTA format 1 deliberately
keeps these boundaries fixed.

## Subsequent remote base updates

Build an OTA-capable target ELF and its matching BIN. For server-backed devices,
archive the new base before switching so subsequent service builds can fetch it:

```sh
./micros server publish-base --firmware build/ota-4mb/micros_runtime.elf
./micros base-update -d DEVICE --firmware build/ota-4mb/micros_runtime.elf --dry-run --json
./micros base-update -d DEVICE --firmware build/ota-4mb/micros_runtime.elf --json
```

The BIN defaults to the ELF's sibling; `--image` selects another path. Preflight
checks the OTA capability marker, device flash size, partition capacity and the
ELF hash embedded in the BIN. A dry run does not acquire a mutation lease.

1. Acquire the existing deployment lease against the expected application selection.
2. Send the image length and SHA-256, then strictly sequential chunks of at most
   4,096 bytes. The running base and application remain selected during transfer.
3. Verify the transfer hash and ESP-IDF image validation, switch boot selection,
   and reboot. Incomplete or rejected images never become boot candidates.
4. The candidate runs management with application execution stopped. An independent
   ESP timer resets an unconfirmed candidate after 180 seconds; the rollback-enabled
   bootloader selects the previous base after that reset or an earlier crash.
5. The client verifies device identity and the exact new base hash, waits for at
   least five seconds of uptime, and explicitly confirms through the authenticated
   connection. A fresh status response must show the new base confirmed.
6. Build/deploy service packages against the newly confirmed ELF. Base confirmation
   does not establish application readiness.

Application writes and lifecycle mutations are rejected during a base trial.
The shared application bytes and ownership metadata remain untouched, so a failed
base trial can return to the previous base. After confirmation, small NVS records
bind admitted application graph hashes to their base hash; packages from another
base remain stopped across reboot. These records are 64 bytes per staging bank,
not image backups. Future NVS schema changes must preserve the old base's ability
to boot until the new base is confirmed.

Direct-only profiles need their paired ELF/sdkconfig refreshed for later ordinary
service builds. An explicit `./micros build --firmware NEW.elf --output DIRECTORY`
can build matching packages without changing pairing. Server-backed deployments
retrieve the matching archived ELF by the board's reported hash.

## Protocol and failure behavior

All five operations use the existing authenticated controller queue and deployment
session. Relay operation IDs 13–17 extend the existing MRL1 envelope; update the
management server before using relay OTA. Base chunks are kept in the server's
volatile private-command storage because firmware can contain credentials.

| Endpoint | Body |
|---|---|
| `POST /v1/base-begin` | 40 bytes: `MBO1`, little-endian image length, 32-byte image SHA-256 |
| `PUT /v1/base-chunk?cursor=N` | 1–4,096 bytes; cursor must equal received byte count |
| `POST /v1/base-finish` | Empty; validate and select the candidate |
| `POST /v1/base-confirm` | Exact current ELF SHA-256, 32 bytes |
| `POST /v1/base-abort` | Empty; release an incomplete upload |

`status.base_ota` reports version, running slot, slot capacity, pending trial,
upload activity, received bytes, chunk limit and trial duration. An expired
lease aborts an unfinished upload. Once boot selection is committed, closing the
session cannot cancel the scheduled reboot or admit another upload before it.

Explicit HTTP 503 admission rejections are retried with bounded backoff. The client
does not blindly retry chunks with uncertain outcomes. It aborts the
upload where possible; retrying starts a fresh transfer. Lost finish/confirmation
responses are resolved by observing device identity and state. Upload resume
across device resets is not implemented.

## Verification and remaining hardware gate

Both 4 MiB and 8 MiB OTA firmware builds link successfully with warnings treated
as errors. Production OTA C code is exercised through simulated IDF calls for
both slots, framing/size/order rejection, partial-transfer rejection, failed writes,
digest mismatch, image-validation failure, boot-selection failure, session cleanup,
trial timeout, confirmation and application ownership. The SHA mock checks stream
accounting; ESP-IDF supplies the actual cryptographic implementation.

The client tests cover dry run, binary/ELF mismatch, capacity rejection, chunk
bounds, unknown outcomes, reconnection, confirmation, rollback observation, both
partition layouts and relay framing/private payloads. Fifteen focused CTest checks
passed. A full 42-check host run passed 41; the unrelated `unit_configuration`
check expects no GPIO for a unit that now declares a DHT GPIO in its existing file.

Before losing physical access, validate on actual boards: initial migration,
successful update, power cuts during transfer/boot selection, unreachable trial
management, crash rollback, retained Wi-Fi/NVS, and application redeployment after
confirmation. The host simulations do not prove bootloader power-loss behavior,
flash timing, physical networking or runtime heap headroom.
