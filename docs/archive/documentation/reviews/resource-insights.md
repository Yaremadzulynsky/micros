# Resource ownership and board insights

Board definitions describe available physical lines. Service capabilities name the
required lines. Generation resolves logical IDs and exposes named opens only for
those grants. Admission rejects conflicting grants; runtime handle acquisition
tracks current ownership. The Feather pixel driver acquires its two GPIO grants
before touching its board-specific waveform registers and releases them on stop.

Base telemetry now includes generated board inventory, flash size, boot recovery
pin, actual GPIO levels, service grants and current usage, separate internal/PSRAM
heap pools, elapsed execution maxima, software timer lateness, Wi-Fi connectivity,
and channel publication/backlog/missed-message measurements. Status is bounded to
the existing 4096-byte response and overflow is rejected instead of returning
truncated JSON. No Wi-Fi passwords, SSIDs or enrollment tokens are reported.

The server correlates service/channel labels only through verified release/base
hashes. Console views and timeline events retain missing-data distinctions for old
firmware. Reservations are not presented as measured allocations, elapsed callback
latency is not presented as CPU load, and retention overwrites are not counted as
subscriber loss until the subscriber reports skipped messages.

Verification includes host capability tests for open-versus-granted resources,
channel backlog and loss/reset tests, label/base/trial mismatch tests, and a
management-only onboarding regression test. Both 8 MiB Feather and 4 MiB
no-controls bases were compiled with the pinned ESP-IDF toolchain.

## Hardware and browser results

Both physical bases were flashed and paired successfully. Feather runs all four
services with GPIO grants/open masks of 3 for Colors (GPIO0/2) and 8 for Button
(GPIO38), and Button reports one open timer out of one permitted. The user confirmed
that button presses still cycle colors. The observed button.state stream had
11 publications, zero reported skips and zero backlog during browser verification.
The WROOM board reports its 4 MiB profile, empty GPIO inventory and the serial
hello-world service.
Both report IP/RSSI/disconnect data and separate heap pools.

Live Feather status occupied approximately 2.5 KiB, within the unchanged 4 KiB
transport limit. Desktop and 390 px mobile browser checks found no JavaScript
errors or page overflow. Compiled bases are identified by the paired ELF hashes
in local private state; no base or private provisioning files are committed.

Host verification: all 29 CTest checks passed across the full run and targeted
reruns after adjusting the expected Colors grant count. The new server cases also
verify receipt label isolation and omission of private configuration/image data.

## Remote wiring migration (graph format 3)

Both boards now run the graph-format-3 base. GPIO names, physical pins, directions
and the recovery-input selection travel inside the checksummed application graph.
The runtime validates them before activation and applies them after stopping the
old application. Rollback restores both wiring and services. Native pixel timing
still lives in the Colors driver, but its data pin comes from generated grants.

The real WROOM was tested entirely through the coordination server after initial
base preparation. `test.remote_gpio` 1.0.0 acquired a named output and drove GPIO25
high; changing only the board definition moved that output to GPIO26 without a
version bump. Device readback reported level 1 and one open GPIO in both cases.
A remote reboot preserved GPIO26. Remote rollback restored GPIO25 at level 1.
The base hash stayed `a9de20beb5d84e463cc3acfd29a86d8d64ef03edf0e7bb6499219bf613ed03f7`
throughout. The normal hello-world application was then restored with an empty
GPIO map, and its greetings were read through the server. These are MCU GPIO
readback checks, not external voltage or timing measurements.

The Feather runs its four services with the original GPIO0/2/13/38 map on base
`a958ff57fc5667684cc768e1e016f8eb9a899fe8f4d3e21dc824166cdb09c489`.
Its status reports active Colors and Button ownership. The reproducible output
fixture is under `tests/fixtures/remote-gpio/`; private run receipts are retained
under `build/usability-review/remote-wiring/`.

Validation: 15 configuration tests, 36 terminal tests, graph byte/persistence and
mixed-binding rejection checks, and all 29 host CTest cases passed. The lifecycle
case timed out during the concurrent run and passed its isolated rerun in 11.9 s.
Relay enrollment has 11 passing tests; console authentication has 10. A minimal
application now inherits its explicitly supplied enrollment's server URL, avoiding
accidental loss of remote management during base preparation.
