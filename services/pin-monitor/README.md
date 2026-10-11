# Pin monitor

Samples one to four exclusively owned input pins and publishes one typed `PinSample` per pin per scan. The service uses a fixed state struct and a bounded step loop: no allocation, timers, threads or networking. Late scans are coalesced instead of replayed.

Use the alias `monitor` and the `samples` publication. The [example recipe](../../examples/pin-monitor/micros.toml) monitors digital GPIO27 and analog GPIO34 and connects the sample stream to the network bridge. Copy its service/configuration/channel declarations into your deployment and select the actual board inputs. Pins must have `direction = "input"`; output grants fail compilation and existing ownership conflicts fail admission.

Settings:

- `sample_interval_ms`: 10–60000 ms; the example uses 100 ms.
- `analog_mask`: bits index the order of `capabilities.gpio`. With `["digital", "analog"]`, `2` selects the second input as analog. Zero monitors every input digitally. Bits beyond the declared list are rejected at initialization.

Digital values are 0/1. ESP32 analog inputs use ADC1 (GPIO32–39 where the board exposes them), 12-bit conversion and 12 dB attenuation. Values are raw counts 0–4095, **not calibrated voltages**. ADC2 is excluded to coexist with Wi-Fi. Unsupported pins/platforms fail initialization. ADC conversion timeouts are published as errors with a zero placeholder value; consumers must check `error` before plotting a value. The host runtime reports analog reads unsupported; host service tests supply simulated ADC values.

Each message includes physical pin number, digital/analog mode, value, read error, acquisition timestamp, scan sequence and publisher epoch. Pins are read sequentially, not simultaneously. Each scan shares a sequence; per-pin timestamps indicate the actual acquisition times. Channel overwrites are explicit on read. The service releases every claimed pin and its publication during stop or partial initialization failure; the BSP restores an analog pin's digital input mode for its next owner.

After deploying the exact recipe, display or record readings through the existing authenticated server:

```sh
build/python/bin/python -m micros_tooling.communication.pin_monitor --device DEVICE_ID --project units/DEVICE_ID.toml
```

This prints CSV suitable for plotting multiple traces on the same `monotonic_us` timeline. It generates its Python decoder from the shared protobuf contract using the existing development dependencies. Ctrl-C stops the reader. Reading does not change the deployed pin set or sampling interval. Relay reads are request-driven and may be slower than acquisition; increase channel depth or sampling interval to retain more history. A graphical live plot is not included.

ADC adds service ABI 0 revision 6. Rebuild the base and all selected services together before deploying to an older base. No deployment or firmware update is performed by the example or tests.

The monitor is diagnostic: it cannot observe pins already owned by another service. Device-specific interpretation, I²C transactions and SPI drivers belong in the service owning that hardware. Pins and modes change through deployment, not remote console commands. This implementation uses existing typed, copying channels rather than adding raw/zero-copy IPC.

Validation: `pin_monitor` compiles the production source with generated configuration/protobuf declarations and simulated GPIO/ADC callbacks. It checks mixed samples, timestamps, cadence, read failures, sequence rollover, invalid masks and partial cleanup. Runtime tests check stale/foreign ADC handles and unsupported-platform behavior. The ESP32 base and native service images are also compile-checked; physical ADC accuracy remains hardware validation.
