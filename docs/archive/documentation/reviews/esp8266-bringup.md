# ESP8266 bring-up validation

Hardware: ESP8266EX, 4 MiB DIO flash, 26 MHz crystal, device `f4cfa2d08ce3`, registered as `esp8266`. Validation date: 2026-09-08.

The adapter uses the common kernel, call0 ABI target 6, shared embedded management controller, and separately linked service images. No existing ESP32-specific implementation was changed. USB installation did not back up the device or erase the entire chip.

## Verified

- Three unchanged demo services (hello, blink, C++) were built, deployed and confirmed over the authenticated relay on base slot B.
- A complete 604,192-byte base image was downloaded over authenticated HTTPS into slot B, booted and confirmed. Its ELF identity was `9bfd978c5422ec8529e1ffb66d0bff6ee90d9732eb48c4aed11829e26a845276`; the former slot A remained available for rollback.
- Early slot A candidates booted but failed network confirmation. Serial logs captured the selector returning to confirmed slot B after the deadline. The reset path was then changed to close TLS, stop Wi-Fi, and restore the ROM loader's 80 MHz clock assumption before restarting. The following B-to-A transfer confirmed successfully (`ota-clean-reset.json`, ELF `2dc217c483d0ec7f7c85b31893e3534953d7bd4a45796ba29e2a4d664734aaee`, 605,280 bytes).
- A deliberately hung 599,520-byte candidate was sent by OTA. The board returned to confirmed slot B with SDK reset reason 7 (`ESP_RST_WDT`), no pending candidate, and its known-good ELF identity unchanged (`2f4b04a3476c5394da97d0bd931e428686f0aad1cdc54ed572e12562183d9222`). Evidence: `hung-recovered.json`.
- All 46 host CTest checks passed, including the ESP8266 selector fault-injection and telemetry tests. The selector tests cover torn records, interrupted attempt commits, corrupted journals and one-attempt candidate selection.
- The SAMD21 regression image built at 80,280 bytes with 11,680 bytes of static RAM. Its existing platform behavior and memory limits remain intact.
- The ESP8266 target ABI layout was checked with the actual cross-compiler. The ELF/BIN binder rejected a deliberately corrupted image.

## Current operating constraints

Services are disabled at the user's request to preserve management and OTA heap headroom. Three running demo services left about 9 KiB of free heap; an established connection without services held about 23 KiB. Early warm-reset connection failures also caused TLS allocation failures without services; successful steady-state operation alone was therefore insufficient validation. The corrected reset path was tested through a full OTA reboot and authenticated confirmation.

The ESP8266 clock adapter now reads the SDK epoch and cycle counter atomically to prevent backward timestamps. A temporary TLS setup-buffer optimization failed hardware validation and was removed; the stock SDK TLS implementation remains in use.

Base OTA replaces the whole base application in one of two 704 KiB partitions. It does not update the selector or partition table. Those changes require USB installation. Settings and the old base's service banks remain outside the overwritten base partition. Services must be rebuilt for a changed base identity.

Local build evidence is under `build/esp8266/`: `ota-bounded.json`, `services-b.json`, `ota-diagnostic-serial.log`, `host-check.log`, and `samd-final-check.log`. These are build/test artifacts, not device backups.
