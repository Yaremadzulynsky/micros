# Feather DHT11 diagnostic

OTA micros service for the Feather ESP32 V2, GPIO 27. With the blue module
facing you and its three pins pointing down, the traced connections are:
left/data to 27, middle/power to 3V, right/ground to GND. The module's measured
roughly 5 kΩ data-to-power resistor supplies the pull-up.

This is a board-specific reference implementation. Its [service contract](service.toml)
declares the fixed data pin and environmental publication. The consuming
application supplies board settings and channel wiring; the SDK does not select
or deploy a default Feather application. See the anonymous
[composition fixture](../../../tests/fixtures/composition/applications/dht-monitor.toml)
for a declaration example.

The driver waits two seconds at startup, requests a frame with at least 20 ms
LOW, and reads every roughly 2.5 seconds. It logs temperature, relative humidity,
and raw bytes, or distinguishes stuck LOW, missing response, incomplete frame,
checksum failure and an implausible all-zero frame. Repeated failures do not by
themselves prove hardware damage; a successful checksum validates communication,
not sensor calibration. No synthetic readings are emitted on failure.

Like the existing NeoPixel driver, this is ESP32-specific native code using
GPIO registers and the 160 MHz CPU cycle counter. The unit requires 160 MHz
and disables dynamic frequency scaling. It acquires the named GPIO grant,
keeps the pin as input at rest, and only enables output with its latch LOW.
The module pull-up raises the line when released. Output routing is restored
on stop. The start pulse uses service steps with interrupts enabled; interrupts
are masked on the service core only for the bounded response capture (roughly
4 ms for a normal frame). GPIO27 is enforced at compile time. The raw register
layout is from the pinned ESP-IDF ESP32 `soc/gpio_reg.h`.

## Environment channel (1.1.0)

`environment.reading` (key 2, interface `micros.environment.reading` v1.0) is a
local IPC channel on each board, using `latest` policy and a single 64-byte slot.
Every sample attempt publishes, including failures. Consumers must check `valid`
and the age of `monotonic_us` before using a value; failed attempts have zeroed
measurement fields, which are not actual zero readings. Timestamps use the board's
monotonic clock, not UTC. `publisher_started_us` and `sequence` identify publisher
restarts and ordering within the current boot. The channel is not a Wi-Fi bridge
between boards.

The protobuf contract is `src/sdk/protos/environment/v1/environment_reading.proto`.
`temperature_tenths_c = 235` means 23.5 °C;
`humidity_tenths_percent = 570` means 57.0% RH.

To let another service consume readings, add this to that unit's configuration:

```toml
[services.consumer.subscriptions.environment]
channel = "environment"
```

After generating/building, use `consumer_environment_open`,
`consumer_environment_read` and `consumer_environment_close` from the generated
`consumer_ipc.h`, with `consumer_environment_message_t`. Handle
`MICROS_ERROR_EMPTY` as no new data, and check `message.valid` on successful reads.
The port adds one handle to the generated resource budget automatically.
