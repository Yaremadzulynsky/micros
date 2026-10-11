# Heap allocation breakdown — 2026-09-08

Internal heap now separates running-service reservations, IPC communication
storage, runtime storage, other allocations and free memory. Hovering Communication
buffers shows named channels, configured payload reservations, retained message
bytes and backlog. Runtime shows bookkeeping/task wrappers and supervisor stack.
Wi-Fi, TLS, RTOS internals and allocator overhead remain unattributed; their
individual sizes are not guessed. Private service arena usage remains unmeasured.

IPC structures are allocated inside the runtime object. Their exact size is
subtracted from runtime metadata before display, preventing double counting.
The current boards allocate 8,448 bytes for channel storage, including 8,192 bytes
of payload capacity. Retained message bytes count meaningful ring contents,
including already-read messages, until overwrite. They are distinct from unread
backlog and from allocated capacity. Accounting is omitted on PSRAM-enabled bases
because default-allocator storage cannot then be assumed to belong to internal RAM.

## Hardware validation

All three bases were rebuilt with their original partition layouts, credentials
and unit recipes. Partition binaries matched the installed originals byte for
byte. Rebuilt services passed local admission before OTA. New base ELFs and
partition metadata were archived on the management server before installation.

| Board | Confirmed base SHA-256 | Running services | Runtime + supervisor bytes |
| --- | --- | ---: | ---: |
| esp32-3b04 | `c98934ada0f19f5d7a753c44c9559dbf842a4485e174fdc42256e6ce79eb87c0` | 1 | 9,372 |
| feather | `46cdce168a76d8c021a4224d605b9d123b3d307b9a091508d4b96b2cb52b310d` | 3 | 10,260 |
| wroom | `7cf8d07c277fd58548fc689e2b04c37569821030a5961db8898af2cf8fb63544` | 2 | 9,816 |

Each board reported the expected new base, no pending OTA trial, running services
and the original confirmed service graph hash. Existing service images remained
compatible after rebuilding against the new bases, so deployment restarted them
without rewriting application flash. Channels reported actual retained payloads,
including Feather's button and environment channels. Heap segments reconcile with
reported internal used/free totals.

The server needed its existing base-OTA route support deployed first; the initial
route rejection occurred before firmware writes. Wroom's relay upload hit gateway
timeouts and was observed aborted, with the original base/services running. Its
successful OTA used the saved certificate-verified Docker direct transport.
No uncertain chunks were replayed.

## Checks and operation

- IPC boundary tests cover retained bytes after reads, ring overwrite and channel
  recreation, plus storage/payload accounting relationships.
- All 10 base-OTA/relay CTest entries passed. The full host suite passed 42/43;
  the unrelated existing unit-configuration test still assumes Wroom has no GPIO,
  while its current unit recipe includes DHT GPIO27. That recipe was preserved.
- Flash, RAM and Wi-Fi browser tests passed, covering hover/focus/Escape, CSP,
  missing measurements and 1200/736/360-pixel widths. RAM assertions also reconcile
  the total and verify communication/runtime previews.
- The actual console and localhost were inspected using real board telemetry.
  Localhost serves local assets and proxies read-only status/history through an
  SSH tunnel with certificate verification; it no longer uses a fixed snapshot.

The tailpi source backup is `~/micros/backups/heap-telemetry-source-before.tar.gz`.
Deployment preserved the existing three Compose files and authentication settings.
Builds, OTA results, captured statuses and browser evidence are in the local
`build/heap-telemetry` directory. Original base artifacts remain archived for recovery.
