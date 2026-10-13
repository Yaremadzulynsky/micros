# Shared capture and access diagnosis

Use this reference to capture existing published data or diagnose capture access
failures. Commands run from the repository root. The maintained helper is
[`src/micros_tooling/diagnostics/collect.py`](../../../../src/micros_tooling/diagnostics/collect.py).

## Capture a published port

Select the deployed service name and published port name for the current
base/graph. Local service declarations are a useful hint, but a different local version
does not establish what the server archived or what the board is running.

For a board confirmed to run `board.pin-monitor` with its `samples` port:

```sh
build/python/bin/python -m micros_tooling.diagnostics.collect \
  --device NAME_OR_ID --service board.pin-monitor --port samples \
  --seconds 15 --output build/INVESTIGATION/pins.jsonl
```

Choose a new output path; the helper refuses to overwrite evidence. It resolves
names against the live roster and opens a shared reader lease. It does not deploy
a service or restart the application. The current helper requires ESP32 with
`ipc_stream: 1`, a declared bridge path and archived published channel metadata. Other
platforms can still be surveyed through supported status/logs and existing tools.

Inspect provenance, decoded samples and the final capture record. Keep error and
gap events. Separate initial retained backlog from new publications using sequence
and acquisition timestamps; constant values with progressing valid samples are
not by themselves a stuck producer. An empty capture or a lost final report is
inconclusive. Capture duration ending does not mean the application passed.
In-flight long polls can extend the nominal window; do not leave readers running
indefinitely. The helper closes its lease and retains partial evidence on failure.

## If a request is rejected

Record the method, hostname, path, HTTP status and sanitized error body. Never
include bearer tokens, cookies or Access headers in evidence. Inspect the actual
request rather than guessing routes from their names.

- **Login/access failure:** distinguish the outer Access login from the server's
  operator bearer token. Follow the configured client's renewal instruction when
  applicable, then retry a read-only roster/status request. Persistent failure is
  an access problem, not proof the board is offline. Do not rotate credentials or
  weaken certificate/authentication checks to get past it.
- **404/unknown route:** the collector sends `POST /v1/streams/DEVICE_ID` to the
  configured **operator** origin, with a 12-digit lowercase hexadecimal device ID
  and no query string. This is not `/devices/DEVICE_ID/v1/streams`. A separate
  device-only listener intentionally returns 404 for operator routes. Compare the
  request with the configured client URL and the deployed server implementation;
  code in the checkout does not prove that server version is installed.
- **400/validation failure:** inspect current status and the payload contract in
  [`src/server/channel_streams.py`](../../../../src/server/channel_streams.py). Missing published channel metadata,
  mismatched service/port, stopped service/bridge, unsupported stream capability,
  or a changed activation can prevent opening a lease. Preserve partial evidence
  across changes and use a fresh lease for the current identity; do not combine
  observations from different activations.
- **Confirmed missing operator endpoint:** identify the server update required
  for `/v1/streams/DEVICE_ID` and continue available status/log diagnosis.
  There is no console-session capture fallback.

The operator route is implemented in [`src/server/relay.py`](../../../../src/server/relay.py);
console routing is in [`src/server/console.py`](../../../../src/server/console.py). Repair or
deploy server code only when that is within the task's scope. Do not mix a shared
capture with manual `IPC READ`/`channels read` on its bridge port: those readers
compete for the underlying cursor and can create the apparent data loss being
investigated. An unavailable capture endpoint alone does not require a board
reflash or a new diagnostic-service deployment.
