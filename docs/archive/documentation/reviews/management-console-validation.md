# Management console validation — 2026-09-06

The web console is served by the existing Docker relay at `/console/`, on the
same HTTPS port as device coordination. No board base update was needed.

## Automated verification

- Existing relay suite: 10 tests passed.
- New console suite: 7 tests passed, covering authenticated routes, CSP,
  same-origin mutations, one-use tickets and cookie flags, logout, enrollment
  retry identity, observation persistence, unsafe upload names, and exact-file
  review before shared transactional deployment.
- Host CTest suite: 28 passed initially; the remaining configuration test assumed
  the editable initial color was always red. It now compares the inherited value
  to the configured value, and its targeted rerun passed. All 29 checks are passing.
- JavaScript syntax check passed.
- Playwright with installed Chrome: real-server login, fleet, board overview,
  reported service slots, log read, deployment screen and mobile layout passed.
  No page errors or mobile horizontal overflow at 390 px. Desktop checked at
  1440 px. Screenshots are in ignored `build/usability-review/console-*.png`.

## Connected hardware

Both `feather` (`e89f6d30e1a8`) and `esp32-no-controls` (`b0a732c8082c`) checked in
through the rebuilt Docker server. The Feather reported four Running services;
the other board reported zero application services with resident management active.

The browser uploaded the Feather's exported recorded release and paired ELF.
Server-side integrity, exact-base and admission review succeeded. Confirming
that release reported **Already current**, preserving the active application.
A separate browser check paused the Feather application and recovered its
confirmed application successfully. No firmware flash, enrollment revocation or
board reboot was performed during this console validation.

## Boundaries

The console currently has one full-access operator role. Browser jobs are bounded
and in memory; a restart or lost browser connection requires checking current board
state before retrying a mutation. Telemetry persists for 24 hours, and Activity is
console operations plus observed boots rather than a complete cross-client audit.
Service labels on the status view are slots because existing firmware does not
report names. The release review does show names and versions from validated
packages. Wi-Fi RSSI is explicitly unavailable rather than fabricated.

Compiled application releases are supported; compilation remains in the CLI.
The server does not retain uploaded private ELFs or act as a firmware build farm.
