# Service test fixtures

These implementations exercise specific runtime behavior and are not starter examples:

- `loader-service/`: initialized data, BSS, arena reset, hook order and three-step assertions.
- `runtime-service/`: repeating timers and simulated GPIO.
- `sensor-pipeline/`: synthetic samples, fast/slow subscribers, queue loss and the legacy hardware LED role.
- `cpp-lifecycle/`: arena placement construction, state retention and explicit destruction.

Existing host tests and release hardware checks build these fixtures. Minimal copyable service interfaces live under `examples/`.
