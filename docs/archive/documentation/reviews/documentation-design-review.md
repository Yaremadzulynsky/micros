# Documentation and design review — 2026-09-06

The documentation pass was followed by implementation of the concrete bugs.
The user chose to retain the prototype limits for base management configuration,
pixel timing and application readiness. No device was flashed or deployed.

## Completed fixes

1. **Empty board map restored.** The user confirmed that the 4 MiB ESP32 has no
   external button/NeoPixel. [`esp32-no-controls.toml`](../../../../config/boards/esp32-no-controls.toml)
   now has no GPIO resources or recovery input. Its existing private profile already
   selects the GPIO-free hello application and an empty map. Offline validation
   accepts hello and rejects the button application on this board.

2. **Button restart semantics fixed.** Button interface minor 1 adds a nonzero
   `publisher_started_us` epoch. Colors and Logger accept a new epoch as a restart;
   invalid ordering within an epoch remains an error. Colors reads retained history
   to establish state but suppresses actions timestamped at/before its subscription.
   Publisher restart, message loss and sequence gaps establish a fresh baseline.
   Subsequent live press edges work normally, without changing stream/latest kernel
   semantics. A new [integration test](../../../../tests/services/button_restart_test.c)
   uses the real runtime ring, generated codecs and production consumers, independently
   reloading publisher/subscriber instances while retaining channel history.

   Button, Logger and Colors versions were bumped and their shared interface now
   requires minor 1. Deploy the enabled participants together. ABI 0 revision 5 is
   unchanged and all four services compile against the existing paired ESP32 base.

3. **Tests and release builds no longer depend on application enablement.**
   [Explicit fixture configuration](../../../../tests/fixtures/configuration/README.md)
   supplies all four services, independent of the editable root application's enabled
   flags and tunables. Host generation includes Logger even when it is disabled in
   the application. Configuration tests and the offline ESP32 config build test use
   the fixture. The release wrapper defaults to a dedicated two-line Feather board;
   `--board` propagates to base generation and packages, including generated logical
   IDs and GPIO bindings. Invalid fixture boards fail before invoking a compiler.

4. **Liveness wording corrected.** CLI deployment progress and console overview
   describe runtime liveness rather than imply that physical wiring or application
   correctness has been verified. Activation policy is unchanged.

## Prototype limits retained by request

- **Management endpoint and trust rotation:** URL, token and trusted certificate
  remain base configuration requiring physical migration. Use a stable hostname
  and retain recovery artifacts. A recoverable authenticated configuration store
  remains future work; no remote credential-rotation protocol was introduced.
- **Pixel timing:** the single-pixel driver still requires a 160 MHz base with
  frequency scaling disabled and briefly masks core-local interrupts. GPIO grants
  remain enforced. A general base-owned waveform peripheral API is deferred.
- **Application readiness:** five-second Running/progress confirmation detects
  startup/liveness failures, not incorrect physical behavior. Application-specific
  readiness signaling and sensor/wiring verification remain deferred.

## Validation

- All 30 host CTest checks passed serially. An earlier parallel run timed out in
  `runtime_lifecycle`; it passed both alone and in the serial suite. The earlier
  generated-schema test collision was fixed by using an unused field number.
- Four focused ASan/UBSan checks passed: button restart, color/debounce behavior,
  codec boundaries and protobuf interoperability.
- All four application services compiled and passed offline graph admission against
  the paired ESP32 base under `build/review-fixes/`.
- The empty board accepts hello and rejects unavailable button grants.
- Patch whitespace and JavaScript/Python syntax checks passed.
- Hardware behavior, base builds and live relay operations were not exercised.
  Historical M0–M8 measurements remain historical evidence.
