# ESP32 services executed from flash

The ESP32 runtime defaults to `CONFIG_MICROS_SERVICE_FLASH=y`. Service instructions
execute through the instruction-cache mapping of the existing service partition.
Read-only service tables and strings use a byte-addressable data-cache alias of
the same physical bytes. Writable initialized data and BSS remain in internal RAM.
The 48-byte ABI descriptor is deliberately retained in the data slot for the
existing native descriptor interface; other `.rodata` is not copied to RAM.

The current [flash linker profile](../../../../src/firmware/platforms/esp32/runtime/main/flash_slots.ld)
exports a 12 KiB combined instruction/constant capacity per service. Earlier flash
profiles used 8 KiB, which tools retain as a fallback when the export is absent.
Read the paired base's exported capacity when building a service. The default
writable slot is now 1 KiB (`CONFIG_MICROS_SERVICE_DATA_BYTES`, 256–4096 bytes),
rather than 4 KiB. Arenas, stacks, channel buffers and startup configuration are
separate budgets. A smaller writable slot is enforced by both the service linker
and device admission. Changing it requires rebuilding the base and its services.

## Image and mapping contract

Format 1 remains available for host images and the legacy RAM-service profile.
Format 2 is ESP32-only and keeps the 64-byte header. Word 12 contains the DROM
address corresponding to the start of the code payload; word 13 contains the
read-only suffix length. Words 14–15 remain zero. The code payload is aligned
instructions/literals followed by aligned read-only data. The descriptor offset
still points into the initialized RAM-data payload. All lengths, alignment,
checksum, addresses, reserved fields and descriptor/hook bounds are checked.
Hooks must point into the instruction prefix, not the read-only suffix.

The existing bank layout and activation journal are unchanged. Both aliases map
one whole 128 KiB bank. Slot payloads begin at `4096 + slot * 16384 + 64` within
that bank. The base exports expected IROM and DROM addresses immediately after
its own page-aligned flash sections. This relies on the pinned ESP-IDF v5.5.2 MMU
allocator; every returned mapping address is checked before exposing a service.
If another mapping occupies that address, admission fails instead of executing
at the wrong address. A future SDK/allocator change needs renewed validation.

A mapped bank cannot be erased or written, including its graph sector. References
hold both mappings until all loaded images are closed. The existing manager joins
service tasks before unloading. Switching banks requires all old mappings to be
released; opening a different bank while references remain fails. Rollback maps
the preserved prior bank into the same virtual slots. Failed mapping setup
releases any partial mapping. No code is copied into IRAM in this profile.

These services must not install cache-independent interrupt handlers: their code
and constants depend on flash being accessible. ESP-IDF manages suspension of
ordinary tasks during flash operations. Hardware timing behavior, including pixel
waveforms during updates, needs on-device validation.

## Enabled features

`CONFIG_MICROS_REMOTE_ENABLED=n` selects a small serial-only implementation and
omits the management server, credential handling and Wi-Fi setup sources. No
Wi-Fi stack is linked into the verified serial-only ELF. Serial deployment,
activation/rollback, GPIO, timers and bank hashing remain supported.
`CONFIG_MICROS_REMOTE_ENABLED=y` retains HTTPS management and Wi-Fi;
`CONFIG_MICROS_RELAY_ENABLED=y` additionally enables the outbound relay. Existing
network provisioning builds continue to enable their provisioned features.
Disabled relay bodies are excluded by their existing compile-time guards.

Use `idf.py menuconfig` in the chosen build directory for these base options.
This is base configuration, not a remote service-setting change. Optional features
are not inferred from today's GPIO bindings, since deployments can change those
bindings without replacing the base.

## Migration and verification

A flash-service base requires rebuilt format-2 service packages. It rejects old
RAM-service packages. Deploy a matching rebuilt application after installing the
new base; a preexisting format-1 bank will not start under the new profile.
Rollback between banks works within a compatible base/image profile, not across
the base migration. No physical device was flashed as part of this implementation.
ESP8266 and SAMD21 loaders are not implemented by this ESP32 change.

Run host validation with `ctest --test-dir build/host -R flash_image_backend`.
With the pinned ESP-IDF environment active, cross-link a 2 KiB read-only table
against all four slots using:

```sh
build/python/bin/python tests/flash/builder_test.py build/flash-network-check/micros_runtime.elf
```

The test verifies that the table is in DROM and mutable variables are in RAM,
while fitting into the new 1 KiB writable-slot limit. Host storage simulations
cover same-bank reference sharing, cross-bank rejection, write protection,
partial-map failure cleanup, release and rollback. These simulations do not
emulate CPU cache execution or prove physical power-loss behavior.

## Build measurements

Historical matched Feather builds from the initial flash-service change, using
its 8 KiB code budgets and pinned compiler (bytes; static figures exclude runtime
heap allocations). These figures have not been remeasured for the current base:

| Profile | IRAM used | Static DRAM used | Firmware image |
| --- | ---: | ---: | ---: |
| Network, legacy RAM slots (4 KiB data each) | 127,099 | 59,848 | 887,767 |
| Network, flash slots (1 KiB data each) | 94,319 | 47,584 | 855,255 |
| Serial-only, flash slots (1 KiB data each) | 52,539 | 16,164 | 231,131 |

The network comparison recovers 32,780 IRAM bytes and 12,264 static DRAM bytes.
Most DRAM recovery comes from reducing four fixed data reservations; moving
constants alone would not reduce unchanged reservations. The current Button and
Colors application compiles against the compact profile; both have 48-byte
initialized data payloads and no BSS, with their working state in separate arenas.
All four slots pass the 2 KiB read-only-table cross-link test. A C++ service and a
legacy RAM-linked C service also compile. The existing 30 host CTest cases passed,
as did the new flash backend suite and focused admission regressions.
