# Management server

The Docker server is a registry and command relay. A resident agent in each ESP
base maintains a reusable HTTPS connection, polls and reports identity/status and receives bounded management
operations. Operators need network access to the server only. Application services
can be stopped while the agent continues to run. The agent does not consume a
service slot, GPIO or service timer budget.

## Run locally

Follow [Server and console](../../docs/site/run-management-server.md) for Docker
prerequisites, local or LAN addresses, certificate trust, named profiles and
headless sign-in. The server includes the console; no frontend build is needed.
From an application created with `micros new`, the LAN flow is:

```sh
./micros server setup --host SERVER_LAN_IP
./micros server start
./micros server devices       # An empty roster is expected initially
./micros server console --trust-info
./micros server console
./micros enroll               # USB installation and automatic climate starter
./micros status -d HARDWARE_ID
./micros logs -d HARDWARE_ID
```

The address is the **Docker host's reachable LAN address**, not its container
address or the board's localhost. Port 8443 is the default; use `setup --port`
for another port. `console --trust-info` prints the selected certificate path.
Default server state lives in `~/.config/micros/server`; named profiles use
`~/.config/micros/servers/NAME` (or the corresponding `XDG_CONFIG_HOME` directory).
Identity, operator token, enrollment tokens and SQLite registry remain there,
mounted persistently into the container. Credentials do not belong in tracked
application TOML or the Docker image.

Enrollment selects the server and builds its address/trust into the base. It
creates the physical board's unit and installs the simulated three-service
starter. For subsequent application changes, run `./micros deploy -d HARDWARE_ID`
from that application. Manual `server enroll` only authorizes a device; it does
not flash firmware or install the starter. See [board setup](../../docs/site/set-up-an-esp32.md)
for the complete supported workflow and recovery behavior.

Normal commands query the configured server first:

```sh
./micros devices           # Enrollment names, IDs, presence and last reported status
./micros status            # Select the sole online device, or prompt among several
./micros deploy            # Same selection, then build and deploy through the server
./micros logs -d feather
./micros stop -d feather
./micros recover -d feather
```

There is no required bind step or USB discovery during these commands. Scripts
with several online devices must provide `-d NAME` or `-d DEVICE_ID`. Offline boards
remain visible in the roster but cannot be selected for work. A server failure is
reported without silently switching transports. Without a configured server,
existing paired devices retain their direct HTTPS network workflow.

Status, logs, deployment and rollback need server access, plus the repository and
compiler for source builds. Deployment reads the live board's base hash and fetches
that exact ELF and matching `sdkconfig` from server storage. A new computer does
not need the board's private pairing backup or device token. Compilation runs
locally; the server is not a build farm or base-firmware OTA service.

Base preparation publishes artifacts automatically when a server is configured.
For an existing build, publish its original ELF and adjacent `sdkconfig`:

```sh
./micros server publish-base --firmware /private/original-build/micros_runtime.elf
./micros server publish-history feather
```

Publish the bases referenced by historical receipts before importing history.
`publish-history` archives packages and recorded confirmation times; it does not
activate anything. Imported old receipts identify authored configuration as
unavailable when it was never saved.

Base bundles are immutable and keyed by the ELF SHA-256. Deployments archive exact
packages, a receipt, authored unit TOML/overlay, and the resolved recipe before
stopping services. Distinct configuration variants for identical packages are also
retained by checksum. Successful activation records a confirmation; an interrupted
attempt retains its packages without claiming success. `rollback` recovers server
history and packages automatically. Console releases also archive their packages
and resolved plan; their base must have been published first.

Artifacts live in the persistent SQLite registry on the server volume. They are
operator-only: agent tokens and unauthenticated requests cannot read or write them.
Base ELFs and `sdkconfig` may contain embedded provisioning secrets, so they are
private artifacts and are included in private server backups. The client verifies
all file hashes and keeps a disposable cache in `.micros/artifacts/bases/HASH/`.
A missing server base fails with an explicit publication command, never a guessed
or freshly rebuilt replacement. Existing direct HTTPS deployments still use their
local pairing.

Registry-only operations do not require a local ELF:

```sh
./micros server devices
./micros server stop DEVICE_ID
./micros server recover DEVICE_ID
./micros server reboot DEVICE_ID
./micros server revoke DEVICE_ID
```

`devices` shows enrolled devices, last contact, online/offline state and service
count. `devices --json` includes the complete last reported status. `status` requests a fresh observation. Thirty seconds without a
check-in marks a device offline. Service names come from deployment receipts in
the normal CLI; enrollment names are administrative labels for whole devices.

## Delivery and security

The operator token grants server administration. A unique device token can poll
and submit results only for that device. Revocation disables that enrollment.
HTTPS validates the server certificate and hostname/IP SAN. The ESP synchronizes
time using SNTP before connecting so certificate validity is checked; it never
falls back to plaintext or disables verification. UDP access to `pool.ntp.org`
is needed after a cold boot. Enrollment tokens and CA changes require a base update.

Only the existing service-management operations are relayed: status, logs,
sessions, bounded image/graph upload, activation, pause, reboot and supported
Wi-Fi profile operations. Saved Wi-Fi passwords are never returned; see
[Wi-Fi settings](#saved-wi-fi-networks-in-settings). There is no arbitrary URL
proxy, shell or generic flash-write endpoint.
The existing device-owned deployment lease still arbitrates direct and relayed
clients. A stopped application does not stop the resident management agent.

A request is dispatched at most once. The ESP retries result delivery, never the
operation. A timeout, disconnect or server restart can leave an uncertain outcome;
the caller must inspect status rather than blindly retry a mutation. Device trial
rollback and abandoned-session recovery remain authoritative. Pending commands
are not replayed after restarting the server. Recent outcomes persist in SQLite;
request bodies are discarded on completion/timeout, with seven-day outcome retention.

## Back up and stop

`./micros backup export /private/path/backup` includes the server identity,
enrollments and a transactionally consistent SQLite snapshot, along with local
pairings. Treat the bundle as private credentials. Restore with `micros backup
import` into empty state while the server is stopped, then start it. A restarted
server marks all devices offline until they check in; unfinished commands become
unknown and are never replayed.

`./micros server shutdown` stops the container without deleting data.
`./micros stop -d NAME` pauses the selected board's application instead.

## Moving to a remote host

The same outbound protocol works behind NAT and across networks. Run the image
with persistent `/state`, expose HTTPS and point the ESP configuration at a stable
DNS name. Keep the server identity/CA consistent or explicitly migrate device trust.
Moving from this temporary LAN URL to another URL requires a physical base update
under the current base-update policy. Choosing a stable hostname before a larger
rollout avoids recurring address changes in device firmware.

This first version targets a small fleet: one server process, SQLite storage,
32 concurrent connections and one in-flight operation per device. Idle long polls
refresh presence every five seconds and wake immediately when work arrives.
It has one operator role. It is not an HA or multi-tenant control plane. Before a
production AWS rollout, establish certificate renewal, backups, operator access
policy and capacity appropriate to the fleet. Do not run multiple replicas against
separate registries and expect shared command ownership.

## Web console

Run `./micros server console` to open the console at the same HTTPS origin as the
relay. The command exchanges your existing operator credentials for a one-use,
60-second sign-in ticket; it does not put the operator token in a URL. You can also
open `/console/` and enter the operator token. For local certificate setup and headless sign-in, follow the
[console connection guide](../../docs/site/run-management-server.md#open-the-console).

The console provides:

- A searchable fleet, online/offline presence, last contact and reported health.
- Per-board service slots, uptime, heap history, base identity and diagnostic logs.
- Confirmed pause, recovery and reboot controls, plus rename and enrollment revocation.
- Board-specific CLI deployment instructions with copyable deploy and dry-run commands.
- Guided USB enrollment through `micros enroll`, plus manual authorization with
  downloadable `relay.token` and `relay-ca.pem` files under Advanced.

Application deployment happens in the terminal. With the CLI configured for this
server, run `micros deploy -d NAME` from your micros project. The CLI builds,
validates compatibility and memory, deploys the application and checks service
liveness. Add `--dry-run` to inspect changes without changing the board. Use
`./micros` when running directly from the repository without micros on your PATH.
**Make a change → Deploy from CLI** shows the command for the selected board and
links back to its running services. Browser upload controls are no longer shown;
the existing authenticated deployment APIs remain compatible.

When using advanced manual authorization, download both enrollment files before
closing the enrollment dialog. A failed enrollment request can be retried in that dialog with
the same token. After losing those files, revoke the enrollment before provisioning
new credentials.

Browser authentication uses random, eight-hour, memory-only sessions in Secure,
HttpOnly, SameSite=Strict cookies. Mutations require same-origin JSON requests;
static assets use a restrictive Content Security Policy with no third-party scripts.
Restarting the server signs out browsers. An interrupted operation may continue;
inspect current status and Activity before retrying. Jobs are not replayed on restart.

Heap/uptime observations are sampled every 30 seconds and retained for 24 hours in
SQLite. The UI shows the latest 50 console events per board; storage keeps at most
5,000 console events overall. Activity includes console operations and observed
reboots, not a complete audit of terminal clients. Older firmware identifies services by runtime index; exact base/graph release records supply names. Physical flash slot numbers may differ from runtime order.
Current bases also report Wi-Fi RSSI and other resource insights described below.

For an eventual public deployment, use a trusted HTTPS certificate and retain the
persistent state volume. This first console has one full-access operator role;
SSO, individual user permissions and a complete cross-client audit are future work.
The app expects TLS at the relay itself; it does not trust forwarded origin headers.

## Resource and health insights

Open **Board → Inspect memory & hardware** for a compact physical flash map. Hover or focus a
partition for details; Services shows one selected-service slot view with image
bytes inside reserved capacity. Escape dismisses the preview. RAM remains separate.
Flash capacity comes from the board. Partition boundaries come from the original
partition-table artifact archived under the board's exact base ELF hash. Publish
the original build with `micros server publish-base --firmware PATH/micros_runtime.elf`
to add its adjacent `partition_table/partition-table.bin` to an older base bundle.
This only enriches server artifacts; it does not flash or change the board layout.

Service image sizes and physical slots are reconstructed from archived packages
and the matching base ELF, and accepted only when the reconstructed graph hash
matches the board's confirmed selection. Pending trials suppress attribution.
Unselected slots and other storage remain unknown; their contents are not assumed
empty, and reserved capacity is not reported as a shared free-space pool. Older
or unarchived bases show capacity with layout unavailable. The partition table
is build metadata, not a live readback of flash.

Heap / RAM uses separate Internal heap and PSRAM bars. Internal heap splits into
numbered running-service arena/stack reservations, measured communication storage,
runtime storage, other usage and free memory. Hover a service for its reservation
and historical stack peak; current private arena usage is not measured.
On no-PSRAM bases, `heap_accounting` separates the fixed IPC channel structures
from runtime metadata so their allocation is counted once. Communication previews
show each channel's configured payload reservation and retained message bytes.
Retained bytes include already-read messages until overwritten; backlog instead
tracks reader progress. Empty buffers still occupy their fixed allocation.
Wi-Fi, TLS, RTOS internals and unattributed allocations remain in Other heap usage;
they are not inferred from changes in total free heap. Older bases fall back to
service reservations and other usage without inventing missing measurements.
Disabled PSRAM stays explicit;
unknown measurements never become zero usage. Previews flip above their bars when
needed to stay in view and support keyboard focus, touch and Escape.

New bases report a `board` inventory generated from the selected board TOML,
`memory` pools, non-secret Wi-Fi `network` measurements and live `channels`.
Each service reports declared GPIO/channel masks, open GPIO/timer/handle counts,
arena and stack reservations, stack watermark and maximum hook/callback durations.
The existing service ABI and 4 KiB status envelope are unchanged. Older bases show
an explicit diagnostics-unavailable message. Graph-format-3 bases receive GPIO
bindings and recovery-input selection with normal remote application deployments;
the preview shows that wiring and rollback restores it with the previous services.
Older bases need an initial USB migration to enable this capability.

Resource details distinguish a configured pin, a service grant, and an open
runtime handle. The recovery input is reserved by the base at boot; the button
service can own it during normal operation. NeoPixel GPIO0/2 now appear in the
Feather definition and the Colors driver must acquire both generated grants.
Native drivers remain trusted code: resource declarations and handle enforcement
are not a hardware memory-protection sandbox for arbitrary native instructions.

Arenas are fixed service reservations. Internal allocations inside those arenas
are not measured. Hook/callback maxima are elapsed durations including scheduling,
not CPU utilization. IPC backlog is the slowest subscriber, capped at channel
depth. Missed counts sum skips actually reported to subscribers, including expected
latest-value coalescing; ring overwrites alone do not imply unread-message loss.

The server retains only service/channel labels from validated release reviews or
authenticated terminal deployment receipts,
keyed by exact base and graph hashes. It applies names only to matching confirmed
selections, never pending trials or a different base. This supplies names for the
existing slot-based firmware protocol without a second editable manifest. New terminal deployments register labels automatically after confirmation.
Review a matching release once to label an older application. Raw package
configuration and uploaded private ELF bytes are not stored in this label catalog.

Activity includes observed application selection, service state/result and Wi-Fi
counter changes, along with contact restoration after a gap. This is sampled
observation, not a complete crash recorder: short faults between check-ins can be
missed. Radio samples share the 24-hour observation retention and reset-related
counters are interpreted per boot.

### Local console without sign-in

To temporarily open the console without a token, set `{"require_token": false}`
in the private server state's `console.json`, then run `./micros server start`.
This exposes console management to anyone who can reach its address. Device
credentials, operator API tokens, and browser same-origin checks stay enabled.
Delete the file or set `require_token` to `true` and restart to restore sign-in.
New server installations require a token by default.

### Cloudflare Access with a separate device route

Run the same relay process with two HTTPS listeners using Docker Compose 2.24.4+
and the `src/server/tunnel.yaml` override:

```sh
docker compose --env-file .env -p micros-management \
  -f src/server/compose.yaml -f src/server/tunnel.yaml up --build -d
```

Both published ports bind to `127.0.0.1`; run `cloudflared` on the Docker host.
For installations with a user/ownership override, include that file before
`src/server/tunnel.yaml` on every update. Do not forward either port from the router.

Configure these tunnel routes, with a final `http_status:404` catch-all:

| Public hostname | Origin service | Authentication |
| --- | --- | --- |
| `console.example.com` | `https://127.0.0.1:8443` | Cloudflare Access for the entire hostname, plus the operator token |
| `devices.example.com` | `https://127.0.0.1:8444` | Existing per-device bearer tokens |

The device listener allows only exact POST `/agent/DEVICE_ID/poll` and
`/agent/DEVICE_ID/result/COMMAND_ID` routes. Console pages, operator APIs,
artifacts, other methods, absolute request targets, and query strings are rejected
before authentication. An operator token or a forged Host/Access header cannot
unlock operator routes on this listener. Both listeners share the same registry
and command queue; do not run separate relay processes against the same state.

Create a self-hosted Access application covering the complete console hostname
(leave its path blank). Allow only the intended email addresses, enable MFA, and
enable **Protect with Access** on the console tunnel route using that application's
team name and AUD tag. Users enroll their own second factor. Do not apply browser
Access authentication to the device hostname. Keep `console.json` token protection
enabled. Keep origin certificate verification enabled and trust the origin CA on
the connector; its certificate must match `127.0.0.1` or the configured origin
server name. The ESP trust bundle must validate Cloudflare's public edge certificate,
which is separate from the Pi's private origin certificate.

For Cloudflare-only browser sign-in, an operator may explicitly set
`{"require_token": false}` in the private `console.json` and restart the relay.
Use this only when the operator listener is restricted to localhost and every
public route to it enforces Access, including tunnel-side JWT validation. This
removes the browser token prompt; operator API and device bearer tokens still
apply. Anyone with direct access to the operator listener can then use its console,
so keep the device hostname on the separate device-only listener.

An old public hostname can temporarily route to the device-only port to preserve
existing device URLs. It must not remain an unprotected route to port 8443.
Firmware hostname/trust migration and reflashing are separate operations.

For terminal access, install `cloudflared`, then set the private operator
`client.json` (and any saved operator relay profiles) to the console URL:

```json
{
  "url": "https://console.example.com",
  "cloudflare_access": true,
  "device_url": "https://devices.example.com"
}
```

```sh
cloudflared access login https://console.example.com
./micros server devices
```

The client reads the cached application token with `cloudflared access token`
and sends it in `Cf-Access-Token`, separately from the existing operator bearer
token. It does not follow authentication redirects or retry mutations. Repeat
login when the Access session expires. `device_url` is used for new enrollment
metadata; it does not change firmware or existing enrollments. The operator CA
file must trust the console hostname's public HTTPS certificate.

Cloudflare references: [tunnel origin parameters](https://developers.cloudflare.com/tunnel/advanced/origin-parameters/),
[Access applications](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/),
and [CLI authentication](https://developers.cloudflare.com/cloudflare-one/tutorials/cli/).


### Saved Wi-Fi networks in Settings

With a compatible base (`network.profiles_api = 1`), the board's Settings tab
accepts three ordered primary networks and one fallback, such as an iPhone
hotspot. Empty primary rows are skipped. A working connection remains active;
when disconnected, the board scans and tries available primaries in order,
then the fallback if no primary connects. Saving does not test new passwords.

Saved passwords are never returned. A blank password keeps the credential for
an existing exact SSID; a new SSID needs a password or explicit Open network.
Saving replaces the complete list in one NVS blob. Existing four-primary USB
lists remain readable; replacing one from the console requires acknowledging
its fourth primary. The USB format still supports four primaries for compatibility.

The dedicated console `/wifi` route uses the normal authenticated MCU session
and binary operations 11 (read) and 12 (write). Password-bearing write commands
are memory-only in the relay; SQLite retains only command metadata and a fixed
success/error result. They never enter console jobs, release archives or logs.
Browser fields clear after submission, logout and page exit. Transport uses TLS;
this feature does not enable encrypted NVS, flash encryption, or a password vault.
Old firmware and offline boards cannot edit settings. A timed-out write has an
unknown outcome: reload the saved list before retrying; writes are never replayed.

Validation: `build/python/bin/python -m unittest discover -s tests/server -p '*_test.py'`,
`build/python/bin/python tests/deployment/wifi_policy_test.py`, and (with Playwright
in `NODE_PATH`) `node tests/server/wifi_browser.cjs`.

PSRAM-capable bases now report each service's `arena_pool` (`RAM` or `PSRAM`).
Internal reservations count only internal arenas and service stacks; PSRAM arenas
have their own service segments. Heap accounting remains valid with the
capability-only PSRAM allocator because ordinary runtime allocations stay internal.
Other PSRAM usage includes allocations not attributed to service arenas.

## Agent access to shared diagnostic captures

Authenticated operators can POST open/read/close requests (open includes `base`, `graph`, `service`, and declared `port`) to
`/v1/streams/DEVICE_ID`. This delegates to the shared channel stream operation,
including exact-release schema validation, per-reader leases, boot/activation checks,
shared device drains and explicit device/reader loss events. Device-only listeners
do not expose this endpoint. The operator token is required even when console
browser authentication is disabled.

The [diagnostic examples](../../examples/diagnostics/README.md) provide a bounded
collector and replay runner. Diagnostic acquisition and replay execute in the
MCU services; this endpoint only exposes the existing evidence transport.

The operator shell uses `GET /v1/inspect/DEVICE_ID` for fresh status with deployed
published port and typed command metadata, `POST /v1/commands/DEVICE_ID` for typed calls,
and the shared `/v1/streams/DEVICE_ID` API for telemetry. These require operator
authentication and are excluded from the public device listener. See the
[interactive shell guide](../../docs/site/interactive-shell.md).

Shared operator metadata, observations and operation exclusion belong to
`management.py`, owned by the registry. `remote.py` adapts that registry to the
device protocol. CLI/API inspection, typed commands and streams use these modules
directly; `console.py` owns browser sessions, tickets and jobs.
