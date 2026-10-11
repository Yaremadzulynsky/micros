# Hello service

The service prints `Hello world` once per second. `start` opens one repeating runtime timer; its callback writes the greeting through `debug_write`; `stop` closes the timer. The first greeting arrives one second after start. `init` and `step` have no work to do.

The ESP32 base configures the UART hardware and routes diagnostics to serial. Services use that shared interface rather than configuring UART registers themselves. On the host, diagnostics go to the runtime log.

Build through the root CMake project. Run `ctest --test-dir build/host -R hello_serial_timer --output-on-failure` to exercise real timers and verify the output interval. The ESP32 service builder uses this source by default; its deployment manifest needs one handle, one timer and no GPIO or channels.

This example is not selected by the board's root deployment recipe. See [the SDK contract](../../docs/archive/documentation/SDK.md) for packaging and lifecycle requirements.

For a paired board, select this application with
`./micros device application NAME --project examples/hello-service/micros.toml`.
Future `./micros deploy -d NAME` commands use it automatically; an explicit
`--project` overrides that default. It needs no GPIO and prints through the
base-owned serial/log interface once per second.
