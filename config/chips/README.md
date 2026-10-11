# Chip capabilities

`esp32.toml` records GPIO directions and internal pulls, fixed ADC mappings,
and RMT matrix routing with its shared channel limit. Sources and their version
are recorded in the file. This is a reviewed snapshot, not a live download at
compose time. Unlisted chips are unknown; adding a file requires checking it
against the vendor SDK and the relevant package documentation.

GPIO groups are disjoint and supply shared input/output/pull capabilities.
`gpio.pins` adds fixed mappings. Routable peripheral eligibility is derived from
its input/output requirements, not duplicated across every pin. This initial
catalogue covers GPIO, ADC and RMT, not every ESP32 peripheral or driver feature.

Board capability metadata lives in `config/boards/capabilities/`. It identifies
the chip, verified exposed/onboard connections, external wiring and runtime
restrictions. It is separate from authored `config/boards/feather.toml` and unit
recipes, which choose the actual connections and service grants.

Inspect without a device:

```sh
./micros pins --profile adafruit_feather_esp32_v2
./micros pins --profile adafruit_feather_esp32_v2 --pin 38
./micros pins --profile adafruit_feather_esp32_v2 --all
./micros pins --profile adafruit_feather_esp32_v2 --json
```

The default view groups service connections, unused header pins and board circuits.
Use `--pin` for a plain-language explanation, `--all` for the full table, or
`--json` for machine-readable capabilities. These view options are mutually exclusive.

The Feather V2's GPIO38 has no internal pulls, but its SW38 button has an onboard
external pull-up. `pull = "none"` disables internal pulls; it does not disconnect
external resistors. Explicit `none` normalizes to existing graph data so the
physical board fingerprint and package bindings remain compatible.

Current limits:

- `up` and `down` are validated against chip hardware, then rejected because the
  current micros graph/runtime does not apply configurable internal pulls yet.
  Accepting and discarding them would be incorrect. Firmware support is separate.
- RMT columns report chip pin eligibility; this does not allocate channels or
  prove that multiple service drivers can use the peripheral concurrently.
- GPIO7/8 are exposed by this board but still reserved by micros' current ESP32
  serial/flash restriction. Hardware capability does not bypass runtime rules.
- GPIO20 is supported by the IDF mask and the Feather/PICO package's SCL mapping;
  it must not be generalized to every ESP32 package's external pinout.
- Unverified board connections and external pulls are reported as unknown.

Changing capabilities must not silently change authored pin assignments. Tests
cover no-pull fingerprint compatibility, unsupported settings, fixed mappings,
board restrictions, and the difference between hardware and runtime support.
