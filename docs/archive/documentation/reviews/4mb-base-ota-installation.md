# 4 MiB base OTA installation — 2026-09-08

Both connected boards were identified through the ESP32 ROM as ESP32-D0WD-V3
revision 3.1 with 4 MiB flash. No flash backups were made, as requested.

| Device | USB port | Installed base ELF SHA-256 | Restored services |
|---|---|---|---|
| b0a732c8082c (wroom / esp32-no-controls) | /dev/cu.usbserial-2110 | 011856c7bd0c162f741549bf60f27b68f694ce96becbd0db1743fcc832851715 | Hello, DHT |
| 24dcc3c13b04 (esp32-3b04) | /dev/cu.usbserial-0001 | c8141eccb2b952eb8877c5a0670b12cebdcce91ce5ff346feecc641dc495b6e1 | DHT |

Each device received its own 917,920-byte base, existing TLS credentials and relay
enrollment, rollback-enabled bootloader, OTA metadata, and generated 4 MiB partition
layout. Flash writes verified successfully. The application store remains shared;
no extra application copies were added for base OTA.

Both boards reconnected using retained Wi-Fi settings. Fresh authenticated relay
status verified the installed ELF hash, OTA version 1, slot 0, no pending update,
and all expected services Running with result 0. The addresses were 192.168.1.191
and 192.168.1.34 respectively. Local pairing and server base artifacts were updated,
and ordinary server-backed service deployment completed successfully.

These installations verify physical flashing, connectivity and service deployment.
A subsequent OTA slot switch, automatic base rollback and power-loss behavior were
not tested on these two boards in this session. See the separate Feather report for
its completed network OTA test and remaining rollback validation.

Private build artifacts and hardware evidence are in
`.micros/ota-installations/b0a732c8082c/` and
`.micros/ota-installations/24dcc3c13b04/`.
