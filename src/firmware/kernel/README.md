# Kernel

`runtime` owns lifecycle workers, admission, resources and deadline supervision
across host, ESP32, ESP8266 and SAMD21. `loader` validates native images;
`ipc` implements bounded channels; `deployment` implements activation records.

Application orchestration belongs to `../controller/application.c`. Platform
operations are declared by `../contracts/include/micros/platform.h` and implemented by
each target. Runtime code supplies no weak backend defaults.
See [architecture](../../../docs/site/architecture.md) and [tests](../../../tests/README.md).
