# Chip capabilities

The catalog contains:

- `esp32.toml`: ESP32 GPIO directions, pulls, ADC mappings and RMT routing.
- `esp8266.toml`: ESP8266EX GPIO0–GPIO16, including GPIO16's different pull
  capability. Its dedicated TOUT ADC pad is not assigned a GPIO number.
- `samd21.toml`: the supported SAMD21G18A package's GPIO directions, pulls and
  fixed ADC mappings. CMSIS numbering uses PAxx = xx and PBxx = 32 + xx;
  Arduino MKR D0–D14/A0–A6 numbers are board mappings, not chip GPIO numbers.

Each file records its reviewed source versions and references. Profiles load
through `micros_tooling.config.chips.load_chip`; no network access is required.
Unlisted chips and package variants are unknown. Hardware capabilities do not
imply that the current runtime implements them: ESP8266 and SAMD21 currently
expose digital GPIO only; their board profiles declare runtime pin restrictions
and numbering. No RMT peripheral is declared for either chip.

GPIO groups are disjoint and supply shared input/output/pull capabilities.
`gpio.pins` adds fixed mappings. Routable peripheral eligibility is derived from
its input/output requirements, not duplicated across every pin. This initial
catalogue covers GPIO, ADC and RMT, not every ESP32 peripheral or driver feature.

Board capability metadata lives in `config/boards/`. It identifies
the chip, verified exposed/onboard connections, external wiring and runtime
restrictions. Application unit recipes choose the actual connections and service grants.

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
