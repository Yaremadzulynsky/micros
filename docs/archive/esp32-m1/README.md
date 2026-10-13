# Historical ESP32 M1 loader

This is the original serial-only loader proof, not the current service runtime.
The ESP-IDF project entry is this directory; source is in `main/`. The original
carrier observations are in `boards/connected-pico-v3-02/README.md`.

With the pinned ESP-IDF environment activated, build without flashing:

```sh
idf.py -C archive/esp32-m1 -B "$PWD/build/esp32-m1" \
  -D SDKCONFIG="$PWD/build/esp32-m1/sdkconfig" build
```

The current ESP32 base lives in `platforms/esp32/runtime/`. Follow
[BUILDING](../documentation/BUILDING.md) for current workflows.

`serial_loader.py` contains the matching transfer client; `hardware_test.py` is
the opt-in test for an already-flashed M1 harness. It is not part of host CTest.
