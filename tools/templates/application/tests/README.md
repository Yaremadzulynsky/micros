# Application tests

Run `./micros test -v` from the application root. `climate_test.py` compiles the
real three services, generated lifecycle, IPC bindings and protobuf codecs.
`flow.c` supplies a deterministic test clock and latest-value bus, with independent
subscriber cursors. It verifies two full temperature cycles, fan hysteresis,
matching sample output, skipped samples for a slow display, stale-data reporting,
recovery, default/selected timer settings and resource cleanup.

No board, operator credentials, external input or wall-clock delays are needed.
The test bus is a fixture, not a replacement for the SDK runtime tests. Host tests
and composition cannot establish that a physical deployment works.
