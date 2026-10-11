# Management relay validation — 2026-09-06

The terminal now discovers network targets from the management server. A resident
ESP32 agent reports presence and executes the existing bounded management protocol
over an outbound, certificate-verified HTTPS connection. The local server runs in
Docker at `https://192.168.0.25:8443` with persistent private state.

## Hardware exercised

| Board | Device ID | Application after validation |
| --- | --- | --- |
| Adafruit Feather ESP32 V2, 8 MiB | `e89f6d30e1a8` | button, logger, colors and C++ services running |
| ESP32-D0WD-V3, 4 MiB, no configured controls | `b0a732c8082c` | no application services; resident management online |

Both boards were physically migrated, preserving full flash backups, enrolled,
configured with the existing Wi-Fi credentials and paired to their exact base ELF.
The Feather base hash is
`e7e40d6a94b62e2ac769e2f0c0594be5b3588f89b9fbe652acb0ad2d56254df3`;
the other board's is
`35aeaeea81b30801e1d286de93ffc87d6a2d3dab7e297109eaa6d8a53655531b`.
These identify the tested artifacts, not a universal firmware image: enrollment
credentials and board definitions are embedded in each base.

## Verified behavior

- The server roster distinguishes online/offline boards and includes last contact
  and cached status. No application service is needed for a board to check in.
- `micros status` auto-selected the sole online device. With both online, an actual
  terminal session offered both and returned live status for the selected Feather.
- Name/ID selection, ambiguous noninteractive selection and missing local build
  pairings are covered by automated checks. Deployment requires the exact paired
  base artifacts; status, logs and control can use server discovery alone.
- Root status/log/stop commands reached the second board through the server before
  local pairing. The agent remained available with zero application services.
- Feather deployment preview and unchanged-application detection passed. A forced
  transfer uploaded all four images plus the graph, activated them and confirmed
  every service Running with result OK. Stop-to-confirmation was 8.797 seconds.
- Repeating the transfer with `logs --follow` active passed in 8.527 seconds.
  Concurrent relay requests are serialized within a bounded deadline. Read-only
  log following retries temporary unavailability, and Ctrl-C ends the stream.
- Pausing the Feather produced zero running service instances while management
  remained available. Recovery restored all four services.
- After restarting Docker, the Feather reconnected and answered a fresh status
  request. Enrollments and stored observations survived the restart.
- All 28 host CTest checks passed. Relay tests cover scoped authentication,
  command/result transport, idempotent result delivery and enrollment retries,
  concurrent requests, timeout/restart behavior, boot changes, discovery and
  transactionally consistent SQLite backups.

An early Feather run showed intermittent connection failures when opening a new
TLS session per heartbeat. The agent now reuses its connection and reconnects on
transport failure; subsequent deployment and restart checks passed. USB resets
also sometimes delayed DHCP by about 70 seconds. Onboarding now allows up to 90
seconds for saved Wi-Fi instead of treating that delay as missing credentials.

## Boundaries

This is a local, small-fleet validation, not an AWS deployment or a long-duration
soak test. Thirty seconds without a poll marks a device offline. The server has
one SQLite registry and one operator role, with bounded connections and one
in-flight command per device. Unknown command outcomes are never automatically
replayed. Application health confirmation is runtime liveness, not a physical
button/LED or business-readiness assertion.

The server URL and trust are currently part of physical base provisioning. A
future remote rollout should choose stable DNS, persistent storage and a
certificate/credential lifecycle before provisioning many devices. See the
[server guide](../../../../src/server/README.md) for setup, daily commands and backups.

Detailed run output remains in ignored `build/usability-review/relay-*` artifacts;
private identities and recovery images remain in ignored `.micros/` and `build/`.
