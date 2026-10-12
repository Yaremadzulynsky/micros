# Arduino MKR WiFi 1010

The SAMD21 platform runs the shared kernel and the same C/C++ service ABI as the
other platforms. Target 5 is little-endian ARMv6-M Thumb/AAPCS with soft float;
The shared ABI is 0 revision 7; analog reads currently return UNSUPPORTED on this platform. Arduino, FreeRTOS, NINA,
USB and flash details live in this platform and its host backend.

## Development workflow

For a management-only installation, use `micros enroll` and select the MKR.
Enrollment installs the pinned library/core dependencies when needed and uses
the existing ARM toolchain. Its USB installation does not back up or restore old
network settings. The separate legacy `init --phase flash` flow below preserves
settings by default.

Use Arduino CLI 1.2.0, Arduino SAMD core 1.8.13, ARM GCC 10.2.1 or newer with
C17/C++17, and the pinned dependencies below. Arduino's bundled GCC 7 is too old.
Run `./micros setup` for the shared Python build dependencies.

```sh
arduino-cli core install arduino:samd@1.8.13
git clone --depth 1 --branch V11.1.0 https://github.com/FreeRTOS/FreeRTOS-Kernel.git build/toolchains/freertos-kernel-v11.1.0
git clone --depth 1 --branch 1.8.14 https://github.com/arduino-libraries/WiFiNINA.git build/toolchains/wifinina-1.8.14
./micros init mkr --platform samd21 --phase prepare --compiler-dir /path/to/arm-gcc/bin
./micros init mkr --platform samd21 --phase flash --compiler-dir /path/to/arm-gcc/bin --project examples/mkr-demo/micros.toml
./micros deploy -d mkr
./micros status -d mkr
./micros logs -d mkr --follow
./micros stop -d mkr
./micros recover -d mkr
./micros rollback -d mkr
./micros reboot -d mkr
./micros wifi setup -d mkr --ssid YOUR_NETWORK
./micros wifi add -d mkr --ssid YOUR_BACKUP --fallback
./micros wifi list -d mkr
./micros wifi status -d mkr
```

`init --phase connect` pairs an already flashed board with its exact base ELF.
`--port` selects a particular MKR; automatic selection rejects ambiguous boards
and never selects an ESP serial port. Double-press Reset if the application no
longer services USB. The bootloader does not expose the application serial number.

Base flashing reads the old flash into a private temporary directory and preserves
the two Wi-Fi settings records. It erases service banks and activation metadata:
rebuild and deploy services against the new base. Plain `arduino-cli upload`
does not perform this preservation. Install layout version 2 over USB once before using base OTA.

The portable demo runs hello, LED blink on D6 and the existing C++ example.
`examples/mkr-ipc/micros.toml` runs the existing button publisher and logger on D7
with generated configuration and protobuf IPC. D7 is pulled up; connect a button
to ground to exercise changes. Services contain no SAMD or Arduino API calls.

## Images and bounded resources

Services are independently compiled into `.msp` packages and a `bank.bin` plus
`report.json`. Code and constants execute from flash; initialized data is copied
to a stable RAM slot. The base hash binds packages to the exact RAM/linker layout.
The host and device check image ranges, Thumb entry points, ABI, checksums, graph
hash, configuration and resource budgets before activation.

| Resource | Limit |
| --- | --- |
| Services | 4 |
| Image storage per service | 9 KiB including envelope (layout 2) |
| Initialized data + BSS per service | 512 bytes |
| Total service stacks | 4 KiB |
| Total arenas | 1 KiB |
| Channel payload storage | 512 bytes |
| Channels / GPIO bindings | 4 / 4 |
| Handles / timers per service | 8 / 8 |
| Configuration per service | 256 bytes |

The MKR has 32 KiB SRAM, so these are admission ceilings rather than ESP-sized
capacity. Allocation can still fail; inspect service status and stack watermarks.
`heap_headroom` is growth space above the libc heap break, not total reusable free
memory. An additional 2 KiB is reserved for the interrupt/main stack.

Layout version 2 partitions all 256 KiB:

| Region | Address | Capacity |
| --- | --- | --- |
| Arduino USB bootloader | 0x00000 | 8 KiB |
| Boot selector reservation | 0x02000 | 6 KiB |
| Service selection journal | 0x03800 | 512 B |
| Base selection journal | 0x03a00 | 512 B |
| Wi-Fi/enrollment records | 0x03c00 | 1 KiB |
| Base A | 0x04000 | 80 KiB |
| Base B | 0x18000 | 80 KiB |
| Service bank 0 | 0x2c000 | 40 KiB |
| Service bank 1 | 0x36000 | 40 KiB |

Each service bank reserves 4 KiB for graph metadata and four 9 KiB image slots.
Rebuild packages for the current base and shared deployment format; older
controller formats are not accepted.

Deployment stops services while writing the inactive bank, then starts a trial.
The journal commits a healthy candidate after five seconds. Failed candidates fall
back to the confirmed graph; interrupted staging times out after the shared controller lease expires.
A watchdog recovers a stalled CPU. Hardware testing is required for any new base.

## Networking and current limits

USB and authenticated TLS relay management are supported. Two Wi-Fi profiles
(primary and fallback) are stored in two checksummed, separately committed records;
passwords are never returned by status. The primary is tried first on reconnect,
then the fallback; a working connection remains active. `wifi setup` sets the
primary, `wifi add --fallback` sets the second network, and `wifi list` returns
saved metadata. Both commands prompt privately for passwords, or accept a local
`--password-file`. Scanning is not implemented.

The optional second-profile extension preserves the original settings layout and
checksum, so older bases can still read the primary and enrollment. Invalid or
absent extensions are ignored; saving both profiles is one atomic transaction.

TLS uses the stock NINA certificate store, with no insecure fallback. The configured
public management endpoint works with the installed trust store. A private server
CA would need provisioning into that store.

## Verification

```sh
build/python/bin/python tests/samd21/abi_test.py --compiler-dir /path/to/arm-gcc/bin
build/python/bin/python tests/samd21/package_test.py
build/python/bin/python tests/samd21/serial_smoke.py --port PORT --serial-number SERIAL --firmware build/samd21/firmware/runtime.ino.elf --compiler-dir /path/to/arm-gcc/bin
```

The hardware test deploys both banks and checks rollback, timer output, GPIO state,
repeated lifecycle operations, rejected partial updates and reboot persistence.
See `docs/archive/documentation/reviews/mkr-samd21-bringup.md` for dated evidence and outstanding issues.

### Management telemetry

The shared controller formats service, GPIO, memory and network status. The
platform supplies measurements through `telemetry.h` and `network.h`. Each
request borrows the shared reserved reply workspace; the relay retains mutation
replies until acknowledgement. Unsupported measurements remain unavailable. Historical
board measurements are in the archived bring-up review; they do not validate a
new base build. Verify live heap headroom and task stack watermarks after changes.

The build copies the pinned WiFiNINA dependency into its output directory and
bounds its SPI receive staging buffer to 256 bytes. A failed allocation returns
no available data before calling the driver; it cannot pass a null buffer to SPI.
The receive path drains larger replies in chunks. Run
`python tests/samd21/socket_buffer_check.py PATH_TO_WIFININA` to exercise allocation
failure, partial reads and cleanup against the actual pinned library source.

## A/B base updates

Build each image for the address where it will execute. The USB-installed selector
remains at 0x2000; OTA can write only the inactive base slot. Arduino’s original
USB bootloader is preserved. The USB reset override enters that bootloader without
erasing a base image.

```sh
# Build both slot-linked images (replace the compiler path).
build/python/bin/python src/micros_tooling/platforms/build_samd21.py --compiler-dir /path/to/arm-gcc/bin --base-slot 0 --output build/samd21-ab/a
build/python/bin/python src/micros_tooling/platforms/build_samd21.py --compiler-dir /path/to/arm-gcc/bin --base-slot 1 --output build/samd21-ab/b
# One-time USB migration, preserving Wi-Fi/enrollment and clearing service banks.
./micros init mkr --platform samd21 --phase flash --firmware build/samd21-ab/a/firmware/runtime.ino.elf --project examples/mkr-demo/micros.toml
# When A is running, validate and upload the image linked for B.
./micros base-update -d mkr --via relay --firmware build/samd21-ab/b/firmware/runtime.ino.elf --dry-run
./micros base-update -d mkr --via relay --firmware build/samd21-ab/b/firmware/runtime.ino.elf
./micros deploy -d mkr --project examples/mkr-demo/micros.toml
```

The relay upload stages one device-scoped image in server memory for up to ten
minutes. The MKR fetches it over one authenticated HTTPS connection into the
inactive slot using a fixed 256-byte buffer; it never buffers a whole base in RAM.
Only that enrolled device can fetch the image. USB updates use bounded chunks.

For the next update while B is running, select the A ELF. Base updates stop service
execution; service packages are bound to the exact base hash and must be rebuilt
and deployed after a successful base change. Unchanged source services remain portable.

The device checks the staged SHA-256 and vectors before writing a candidate record.
The selector validates image CRCs and commits one trial attempt before jumping.
The candidate confirms only after five seconds and a successful management-server
exchange; failure to confirm within thirty seconds resets into the previous good
base. A startup watchdog covers a candidate that never reaches the runtime. The
selector and settings are outside both base slots. Base staging expires after
180 seconds without an accepted chunk or download request; a bulk download is
bounded to 90 seconds. Duplicate chunks are acknowledged only when
the already-written flash matches exactly; activation is never blindly replayed.

Journal records fit one 64-byte page with CRC and a commit marker; alternating
256-byte erase rows preserve the last valid selection after an interrupted write.
This is an A/B application-base updater, not an updater for the USB bootloader,
selector, or NINA coprocessor firmware.
