# Connected PICO V3-02 Board

Status: Selected serial-only M0 bring-up profile; carrier model unknown.

Observed on 2026-09-05 using esptool.py 4.6.2: ESP32-PICO-V3-02 revision v3.0, 40 MHz crystal, 8 MB flash, embedded PSRAM reported but capacity unverified. Last observed macOS port: `/dev/cu.usbserial-564E0535011` (not a portable identifier).

USB registry reports `USB Single Serial`, VID `0x1a86`, PID `0x55d4`. Adapter identity does not identify the board. M1 uses the existing serial path and no application GPIO. Carrier pin mapping, usable PSRAM, flash mode, and current partition layout must be checked before peripheral bring-up or selecting flash settings. No device write occurs as part of M0.
