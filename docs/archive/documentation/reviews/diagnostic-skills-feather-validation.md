# Diagnostic skills on the Feather

Tested on 2026-09-14 using the three repository diagnostic skills and their
installation/device-access procedures. The user authorized temporary replacement
of the running application for testing, followed by exact-release restoration.

## Target and baseline

- Device: `feather`, authenticated ID `e89f6d30e1a8`.
- Platform: Feather ESP32 V2, four service slots, ABI 0 revision 7, graph format 3,
  `ipc_stream: 1`.
- Base: `b239aa5d5cb8213a27b5f8c073f22fe0aaba2c4611025dcbaed6c045842bf6e8`.
- Starting release: `911d58d20737b9228753cd23bf8d793c1f12e7e66faa2a1b30f914475854daea`.
- Starting graph: `672aea535bdf25da586460b190b59d1b19ec309bc6e68fc74cff608d8eb28156`,
  activation sequence 51. IR, console, pin monitor and bridge were Running.

The baseline shared pin capture returned valid digital/ADC records and a device
gap reporting 13,194 missed records. This was retained as transport/backlog
evidence, not interpreted as physical sensor failure. GPIO38 was already the
declared onboard button input; the recorder used digital input mode on that pin.

## Replay and missing-data workflow

Deployed replay-source, channel-probe and bridge. No replay messages were routed
to physical actuators. Run 91401 loaded three synthetic PinSample messages with
values 0, 1, 0 at offsets 0, 100 and 500 milliseconds. The runner observed each
LOAD acknowledgement before START.

- Replay completed with `phase=3`, `loaded_mask=7`, `published=3`, no rejected
  commands and no last error. Maximum reported lateness was 1,124 microseconds.
- The probe first observed silence, then exactly three decodable messages. Its
  terminal reason was the configured three-message limit, with zero decode
  errors, loss notifications or last error.
- Eight probe report events were collected with no capture gaps. Its maximum
  silence included the intentional initial wait before replay; this is not a
  measurement of message transmission latency.

This validates bounded replay publication and independent subscriber receipt.
It does not establish application domain semantics or physical output behavior.

## Signal-quality workflow

Deployed signal-recorder and bridge, configured for first-valid-sample trigger,
100 ms polling, 16 post-trigger readings and no pre-trigger samples.

- Acquisition completed with `triggered=true`, `done=true`, reason 1.
- All 17 readings were retained, published and collected in five batches.
- Flattened sample indices were exactly 0 through 16 with increasing MCU
  timestamps, GPIO38 and no sample errors.
- No read errors, skipped scans or capture gaps occurred. All readings were high.
- Observed sample intervals were 100,500–105,784 microseconds.

This validates finite digital acquisition, batching and remote collection.
Physical rising/falling triggers, ADC accuracy and high-speed pulse capture were
not tested. No button press was required or inferred.

## Integration findings

The live checks exposed and resolved missing device-name resolution in the new
collection/replay helpers. They now resolve names against the authenticated live
roster, with regression coverage for name, ID and unknown-device selection.

The existing tailpi server needed the new operator capture endpoint. Only the
seven-line route addition was applied to its existing source; the current server
deployment's other code and all three Compose files were preserved. Source backup:
`/home/ydzulynsky/micros/backups/diagnostics-20260914/relay.py`.
Certificate-verified origin checks returned 401 for an unauthenticated operator
request and 404 on the device-only listener. Authenticated capture succeeded.

The four-schema package limit prevents putting all five diagnostic command/report
schemas into a single bridge. The test used two application deployments, and the
installation skill now documents this constraint. The changed bridge contracts
used distinct versions 1.2.0 and 1.2.1 instead of reusing the original 1.1.0 identity.

The legacy `micros release` export path uses the saved local pairing's base and
rejected the current server-backed release because that pairing was stale.
Exact rollback preview passed against the authenticated current base. A separate
release bundle was saved using the verified cached base and immutable snapshot
packages; no pairing, firmware or credential replacement was necessary.

## Evidence and restoration

Local evidence is under `build/diagnostics-feather/`: baseline status/logs,
the original compiled release bundle, reviewed test recipes, deployment receipts,
JSONL captures, `verified-results.json` and server checks. These build artifacts
are ignored rather than committed.

Restoration was verified at activation sequence 60: the exact starting release
and package hashes are selected, all four original services are Running with
result 0, and the base identity is unchanged. The restored application is in bank
1 with graph `567179215db79d4e0e2e9247abd505546fdc84c7d29bb239935164f9dc409703`,
matching the starting release's recorded bank-1 digest. Bank-specific graph
digests differ; restoration checks the release's digest for the selected bank.
Evidence: `restoration.json`, `final-status.json` and `restoration-verified.json`.

The targeted diagnostic host tests and documentation build passed after the
helper/skill corrections. No resident ABI update, base reflash or GPIO output
test was performed. The server capture endpoint remains installed.
