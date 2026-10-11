# MKR WiFi 1010 initial bring-up — 2026-09-08

The pre-port checkpoint is `09c6552`. All 43 existing host tests passed before
starting the SAMD21 implementation. Earlier work was saved in four themed
commits before this checkpoint, including its already-existing ESP32 changes.

The first SAMD21 firmware was compiled with Arduino SAMD 1.8.13, ARM GCC 10.2.1
and FreeRTOS V11.1.0 and flashed over the MKR's native USB bootloader. The upload
tool verified the written flash checksum successfully. No server connection or
ESP32 device was needed.

Observed on hardware:

- The unchanged hello service emits a periodic greeting through the kernel timer
  API and SAMD USB diagnostics.
- Status reports target 5, one service, one worker and no reboot required.
- Five stop/unload/reload/start cycles pass. No timer output occurs after stop
  completes, and the libc heap break stays stable across the cycles.
- The initial build uses 26,196 bytes of program storage and 3,256 bytes of
  static RAM. After startup the heap has 9,996 bytes of growth space below the
  separately reserved 2 KiB interrupt/main stack. This is not a peak-RAM claim.
- Reported runtime metadata is 4,980 bytes while the worker is running.
- ARM C/C++ cross-compiler layout checks pass; Cortex-M3 and big-endian ARM
  builds are rejected as unsupported profiles.
- The existing 43-test host regression suite also passes after the target
  registration change. The SAMD21 BSP compiles with `-Wall -Wextra -Werror`.
- A second USB upload/reset succeeds with checksum verification, preserving
  bootloader access after the FreeRTOS firmware is installed.

Local detailed output is under `build/samd21/serial-smoke.json`; build/upload
logs are in `build/mkr-build.log` and `build/mkr-upload.log`.

This validates a resident service bring-up, not independent service replacement,
network deployment, persistence, flash rollback, GPIO electrical behavior or
long-duration clock rollover. See the platform README for remaining milestones.


## Independent services, management and A/B updates — 2026-09-08

The later platform now loads independently built ARM service packages, validates
and activates durable service banks, and uses the existing authenticated management
relay. Resource telemetry expands into the common Resources and Network pages.
Unused service capacity is shown as reserved capacity, rather than reported as
measured occupied flash. The firmware uses the stock NINA 1.4.8 trust store.

A/B layout version 2 preserves the original 8 KiB Arduino USB bootloader and adds
a selector, two 80 KiB base slots and two 40 KiB service banks. Each service bank
contains 4 KiB graph metadata and four 9 KiB image slots. USB migration preserves
Wi-Fi and enrollment records. A base update leaves service storage intact, but
services must be rebuilt for the new base hash before deployment.

Hardware evidence:

- USB base A → B update and network-health confirmation passed.
- A deliberately non-starting candidate was staged in inactive A. The hardware
  watchdog reset it and the selector restored confirmed B automatically.
- Initial selector testing exposed an NVM address-register issue: page-buffer
  clear must not reset the address into the protected Arduino bootloader. The
  corrected selector passed the real switch and watchdog-fallback tests.
- Bulk HTTPS base A → B and B → A updates passed through the public management
  endpoint. Downloads use a bounded buffer, validate SHA-256 and vectors, then
  commit the trial record. No insecure TLS mode or NINA modification was used.
- Two-profile firmware was itself delivered by OTA. Forcing a connection to an
  unavailable primary selected the existing network as fallback. Duplicate
  profiles and attempts to retain an unknown secret were rejected atomically;
  the original primary and password were restored afterward.
- All 43 host regression tests passed together. All 18 SAMD Python tests, the
  bounded/streaming HTTP parser test, and ARM C/C++ ABI checks passed.

Local evidence is under `build/mkr-ab-wifi-bulk.log`,
`build/mkr-two-network-ota.log`, `build/mkr-ab-fallback.log`,
`build/mkr-two-network-hardware.log`, and `build/mkr-final-host-tests.log`.
These logs contain metadata, not Wi-Fi passwords. Private flash/settings backups
remain outside version control. ESP-specific files still match checkpoint
`09c6552`; only shared additive adapters and SAMD files were changed for the port.


The subsequent service smoke test passed both deployments, service-bank rollback,
GPIO levels, timer logs, five lifecycle cycles, rejected partial-bank activation,
and reboot persistence (`build/mkr-ab-service-smoke.log`). A later base update
started with all three demo services running and confirmed successfully; rebuilding
and redeploying restored all three as Running in the live management roster.
DzulynskyHome was primary and BELL986 was saved as a secured fallback.

The new SAMD Python and HTTP tests are registered in CTest and passed as two
additional checks. The final source removes a redundant settings-structure copy
to reduce controller stack use. Its A/B images compile to 80,256 bytes each,
leaving 1,664 bytes in each base slot. The OTA attempt delivering that last stack
change lost both USB visibility and network presence; its outcome is unknown
pending confirmation that the MKR remains powered and connected. Do not infer
that this final revision was confirmed from the earlier successful update logs.
