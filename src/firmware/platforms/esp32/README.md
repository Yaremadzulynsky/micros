# ESP32 platform

The current runtime targets the original ESP32 with ESP-IDF v5.5.2. The validated Feather V2 uses ESP32-PICO-V3-02 and 8 MiB flash; board definitions also support a 4 MiB layout. Runtime arenas, stacks and service slots use internal RAM, not PSRAM.

`sdk/` is the current base: FreeRTOS service execution, four fixed native slots, persistent activation/recovery, USB control and optional direct HTTPS/outbound server management. `src/` contains the platform contract implementations. Hardware definitions live in the root [`config/boards/`](../../../../config/boards) directory; see [configuration](../../../../docs/archive/documentation/CONFIGURATION.md) for deployment-owned GPIO bindings and physical base limits.

[`docs/archive/esp32-m1/`](../../../../docs/archive/esp32-m1/README.md) preserves the historical M1 serial loader harness and unidentified-carrier bring-up record. They are not the current application runtime. Use [BUILDING](../../../../docs/archive/documentation/BUILDING.md) and [ONBOARDING](../../../../docs/archive/documentation/ONBOARDING.md) for current builds and physical migration.
