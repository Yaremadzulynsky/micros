# ESP8266 platform

This adapter runs the common microS kernel and embedded controller on an ESP8266EX with 4 MiB flash. Services use the Xtensa **call0** ABI (target 6), separately from ESP32's windowed ABI.

The SDK, compiler, generated firmware and device credentials stay outside source control. No device backup is performed by the platform tools.

The pinned SDK startup clears the previous boot's CPU stack watchpoint before
initializing static RAM. Runtime stack watchpoints remain enabled. This prevents
a warm reset from mistaking `.bss` initialization of a static task stack for an
overflow in the previous boot's task.

The build also restores the vendor's thread-local deletion callback fields in
`StaticTask_t`. Its unpatched declaration omits those fields and is smaller than
the scheduler's actual task record. An unconditional compile-time assertion in
the scheduler checks that static task storage matches the real record, even when
the SDK disables `configASSERT`.

## Build dependencies

`micros enroll` and `micros init NAME --platform esp8266 --phase prepare` install the pinned ESP8266 SDK, compiler and isolated Python
packages automatically when missing. Python 3.10, CMake and Ninja must be on PATH.
On Apple Silicon the pinned macOS compiler runs through Rosetta. Setup verifies
the SDK revision and compiler archive hash; it does not flash a board.

The tested macOS toolchain is Espressif's ESP8266 RTOS SDK v3.4, commit `89a3f254b63819035f65d9c5dcdae8864f1a6a8a`, with its `xtensa-lx106-elf` GCC 8.4.0 compiler. Obtain them from [Espressif's SDK](https://github.com/espressif/ESP8266_RTOS_SDK/tree/v3.4) and [macOS setup instructions](https://docs.espressif.com/projects/esp8266-rtos-sdk/en/v3.4/get-started/macos-setup.html). The SDK must include its pinned submodules.

Default paths:

- `build/toolchains/esp8266-rtos-sdk-v3.4`
- `build/toolchains/xtensa-lx106-elf/bin`
- `build/esp8266/python/bin/python` (isolated Python 3.10 environment)

The old SDK requires `pyparsing==2.3.1`, `setuptools<81`, `pyserial`, `future`, `click`, `cryptography`, and `pyelftools`. On Python 3.10 its pyparsing also needs the `collections` compatibility aliases from `collections.abc`. This compatibility adjustment belongs only in that environment's `sitecustomize.py`.

Build with:

```sh
./micros init esp8266 --platform esp8266 --phase prepare
./micros init esp8266 --platform esp8266 --phase flash --port /dev/cu.usbserial-0001
```

The build script adds the microS boot selector to the **isolated ESP8266 SDK copy**, using the pinned original source as its input. It validates and seals the resulting binary against every loadable ELF section, then records the ELF identity in the application descriptor. Never flash the unfinalized SDK binary directly.

`init --phase flash` installs the selector, partition table, slot A base and initial boot journal; it preserves Wi-Fi NVS. It explicitly selects the ESP8266 chip and does not erase the entire flash. `init --phase connect` pairs an already installed base without flashing. Serial opening on some CP2102 drivers resets the board; relay commands avoid that reset.

## Network and management

Enroll the board's MAC identity with `micros server enroll`, then supply the resulting directory with `init --phase connect --relay-credentials ...`. Enter passwords privately:

```sh
./micros wifi setup --platform esp8266 --ssid NETWORK
./micros wifi add --platform esp8266 --ssid FALLBACK
```

Two network profiles are stored on the board. The management network page can edit them without returning passwords. The board validates TLS certificates and hostnames after obtaining network time. The public root bundle includes ISRG Root X1 and GTS Root R4; the latter comes from [Google's root repository](https://pki.goog/roots.pem). Update the bundle when changing to a relay with a different trust chain.

```sh
./micros status -d esp8266 --via relay
./micros deploy -d esp8266 --via relay --project examples/esp8266-demo/micros.toml
./micros logs -d esp8266 --via relay
```

## Flash and service limits

Each 1 MiB execution window contains one 704 KiB base partition and two 128 KiB service banks. Each service bank has a 4 KiB graph and four 31 KiB image slots. Service images contain a 64-byte envelope; each service has 1 KiB of linked RAM. Admission also bounds arenas to 4 KiB, total service stacks to 12 KiB and channel payload storage to 1 KiB. The combined application must also fit an 8 KiB static pool, including service stacks,
configuration, arenas, channel storage and allocation overhead. Service stacks
are reserved during admission before hooks run. Runtime and RTOS bookkeeping are
static, and a separate 2304-byte pool is reserved for management staging. Application
allocations cannot consume the library heap. Wi-Fi and TLS still use SDK-managed
heap memory, so their measured peak remains part of the total RAM budget.

The build removes duplicate certificates before freezing the relay trust bundle,
so mbedTLS does not allocate another parsed chain entry for the same root.
It also stores the validated roots as immutable DER in flash. The pinned SDK
receives a narrow backport of Mbed TLS's `mbedtls_x509_crt_parse_der_nocopy`
ownership model: only these static trust buffers are borrowed; ordinary and peer
certificate parsing still owns its buffers. All configured roots and verification
rules are retained. The bundled nine roots avoid 8,897 bytes of duplicate heap
storage, plus temporary PEM decoding buffers. `tests/esp8266/tls_trust_test.c`
compares copying and borrowed parsing, verification and malformed-input cleanup
with the pinned libraries under AddressSanitizer.
After preparing a base build, run it with
`python tests/esp8266/tls_trust_check.py SDK_PATH BASE_BUILD_PATH`.

The pinned SDK uses dynamic TLS record buffers. The build patches its initial
TLS setup to allocate only header space, which the SDK wrapper replaces before
record I/O. This avoids a temporary 16 KiB allocation that can prevent console
reconnection with an application running. Incoming records still support the
full 16 KiB limit, and certificate and hostname verification remain enabled.
Elliptic-curve calculations use a window of four with fixed-point caching;
integer exponentiation retains a window of two. The former window of two with
caching disabled made an ESP8266 handshake take about 18 seconds, and the public
endpoint closed the connection before completion. The current configuration
completed the same handshake in about 6.6 seconds on a management-only board.
Application memory headroom must still be checked separately. These settings do
not reduce key sizes or bypass verification. Handshake failures include the
protocol state in the serial diagnostic log. For a diagnostic build, pass
`--tls-diagnostics` to `src/micros_tooling/platforms/build_esp8266.py` to log each
step's time, heap, cipher ID and result without logging keys or payloads. Omit
that flag for production firmware.

Background service `step` hooks use a 10 ms polling interval on this single-core
target. Polling three services every millisecond can consume enough scheduler
time to push a fresh TLS handshake past the endpoint's deadline. Timer callbacks
retain their independent deadlines; channel dispatch through a step can take up
to one polling interval, plus scheduling delay.

During a candidate boot, journal checks run at most ten times per second. Flash
reads briefly mask interrupts on this chip, so they must not run on every 1 ms
management tick while TLS connects. The ten-second minimum confirmation period
and three-minute fallback deadline remain in place.

The boot journal uses two separate sectors at `0x100000`. NVS, SDK OTA metadata and radio calibration are outside the base partitions. The remaining 2 MiB plus 56 KiB is unallocated, and the flash view labels it accordingly.

GPIO 1/3 are reserved for UART and 6–11 for the flash interface. The default LED binding is GPIO 2. Boot-strapping pins remain subject to the board's electrical requirements.

## Base OTA

```sh
./micros base-update -d esp8266 --via relay --firmware build/esp8266/firmware/micros_esp8266.elf --dry-run
./micros base-update -d esp8266 --via relay --firmware build/esp8266/firmware/micros_esp8266.elf
```

The full base image is authenticated, downloaded into the inactive partition and checked with SHA-256 and the SDK image verifier. A committed journal records one trial attempt before booting it. The candidate must return to management and confirm; otherwise a watchdog/reset or the 180-second confirmation deadline returns to the previous base. The original ROM serial downloader remains available.

Console downloads use 1 KiB HTTP ranges to bound peak TLS memory. Interrupted
ranges retry at most three times within the transfer deadline; duplicate flash
chunks must match the bytes already written. USB chunk retries additionally
check the unchanged base, staging slot and write position. Activation is not
replayed after an uncertain response.

Base updates preserve settings and leave the old base's service banks available for rollback. Services are tied to an exact base ELF and must be rebuilt/deployed for a changed base. Base OTA does not rewrite the selector or partition table; changing that layout requires USB installation.
