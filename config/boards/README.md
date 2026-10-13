# Board capability profiles

- `adafruit_feather_esp32_v2.toml`: verified Feather ESP32 V2 connections.
- `esp32_wroom_32e.toml`: ESP32-WROOM-32E flash-only N4/N8/H4/H8 module pads.
  Defaults to 4 MiB; set `board.flash_mb = 8` for N8/H8. GPIO16/17 are available,
  GPIO20/37/38 are not led out, and flash/UART pins remain reserved. Carrier
  buttons, LEDs and pull resistors are not assumed. R2 PSRAM variants and 16 MiB
  firmware layouts are outside this profile's scope.
- `esp8266_4mb.toml`: generic ESP8266EX with 4 MiB external flash. Numbers are
  GPIO numbers. Available GPIOs describe the runtime interface; they do not
  guarantee a particular module exposes a header or has no attached circuit.
- `arduino_mkr_wifi_1010.toml`: MKR WiFi 1010 with SAMD21G18A. Numbers follow
  Arduino: D0–D14 = 0–14 and A0–A6 = 15–21. USB, NINA, battery and other internal
  connections are listed with their Arduino indices and reserved by the runtime.

Each profile selects a chip from `config/chips/`. A board using different pin
numbers declares `chip_pin` in every `[gpio.NUMBER]` entry. The loader resolves
chip directions, pulls and ADC mappings into board numbering before validation
or listing. For SAMD21, chip numbers use PAxx = xx and PBxx = 32 + xx.
`exposed`, `onboard`, and runtime `reserved` lists all use board numbering.

`[runtime]` records software limits separately from electrical capabilities.
ESP8266 and MKR currently allow four digital GPIO resources, no configurable
internal pulls, no analog GPIO, and no application recovery-button binding.
Their Python adapters use these declarations and keep existing serialized
bindings and board fingerprints unchanged. Application wiring, services and
physical device identity still belong in the application's unit file.

Inspect offline:

```sh
./micros pins --profile esp32_wroom_32e --pin 16
./micros pins --profile esp8266_4mb
./micros pins --profile esp8266_4mb --pin 16
./micros pins --profile arduino_mkr_wifi_1010 --pin 15
./micros pins --profile arduino_mkr_wifi_1010 --all
./micros pins --profile arduino_mkr_wifi_1010 --json
```

Source references are recorded in the profiles. Board metadata does not enable
new firmware features or verify the user's physical wiring.
