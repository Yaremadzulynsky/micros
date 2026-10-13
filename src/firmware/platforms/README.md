# Platforms

Every target follows [the same contract map](../contracts/README.md).

- `posix/`: macOS ARM64 and Linux ARM64/x86-64 execution with simulated GPIO.
- `esp32/`: ESP-IDF tasks, flash mapping and HTTPS/relay transport.
- `esp8266/`: call0 native execution, flash and Wi-Fi transport.
- `samd21/`: MKR WiFi 1010 execution, flash and WiFiNINA transport.

Open `src/platform`, `storage`, `transport`, `network`, `update` or `telemetry`
(`.c`/`.cpp`) for the corresponding implementation. `src/support/` contains private
helpers; `target_config.h` declares support and budgets; `sdk/` owns startup,
build and boot integration. No target supplies its own application controller.

Application services use `src/sdk/abi/include/micros/`. The shared framework lives
in `../controller/` and `../kernel/`; its headers are separate from platform contracts.
