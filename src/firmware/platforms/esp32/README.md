# ESP32 platform

The current runtime targets the original ESP32 with ESP-IDF v5.5.2. The validated Feather V2 uses ESP32-PICO-V3-02 and 8 MiB flash; board definitions also support a 4 MiB layout. Worker stacks and writable service images use internal RAM. Service arenas can
use PSRAM only when both the board profile and paired base support it.

`sdk/` is the current base: FreeRTOS service execution, four fixed native slots, persistent activation/recovery, USB control and optional direct HTTPS/outbound server management. `src/` contains the platform contract implementations. Hardware definitions live in the root [`config/boards/`](../../../../config/boards) directory; see [unit configuration](../../../../docs/site/unit-configuration.md) for deployment-owned GPIO bindings and physical base limits.

[`docs/archive/esp32-m1/`](../../../../docs/archive/esp32-m1/README.md) preserves the historical M1 serial loader harness and unidentified-carrier bring-up record. They are not the current application runtime. Use [Quickstart](../../../../docs/site/get-started.md),
[enrollment help](../../../../docs/site/set-up-an-esp32.md), and
[base updates](../../../../docs/site/update-the-base.md) for the current workflow.
