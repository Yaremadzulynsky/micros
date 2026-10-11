# Shared host tooling

This Python package is shared by the micros CLI, management server, and tests.
Run the primary command through `./micros`; run module commands from the repository
root with `build/python/bin/python -m micros_tooling.PACKAGE.MODULE`.
Dependencies are installed by `./micros setup` from `tools/requirements-dev.txt`.
The package currently operates within a repository checkout; it is not a standalone
installed distribution of the firmware sources or toolchains.

| Package | Ownership |
| --- | --- |
| `config/` | TOML composition/resolution, board resources, protobuf and API generation |
| `platforms/` | Target-specific SDK setup, application/firmware builders, graph encoders and transports |
| `deployment/` | Provisioning, onboarding, admission, update transactions and diagnostics |
| `communication/` | Remote requests, Wi-Fi setup, channels, protobuf metadata and log access |
| `fleet/` | Management-server administration, discovery and coordination admission |
| `storage/` | Native image/package formats, artifacts, local state and retention |
| `host/` | Desktop native runtime controller and activation |
| `diagnostics/` | Transport/evidence collection and replay command encoding for MCU diagnostic services |

The CLI and server import this package directly. Firmware C/C++ sources follow the
[firmware ownership map](../firmware/README.md); target-specific Python helpers live here. Test fixtures and example-package builders remain in `tests/` and `tools/`.

`cli.py` resolves the application and SDK once. `config/application.py` applies
project defaults, then calls `dispatch.py`, the shared command parser and operation
dispatcher. Shell and installed entrypoints use this same path; SDK switching is
the only Python CLI handoff. `micros sdk COMMAND` bypasses application defaults.

ESP32 application compilation and serial graph encoding live in
`platforms/esp32/application.py` and `platforms/esp32/device.py`. The host builder
lives in `host/build.py`; SAMD21 and ESP8266 share `platforms/embedded/build.py`.
Shared configuration and package validation must not choose a target compiler.
