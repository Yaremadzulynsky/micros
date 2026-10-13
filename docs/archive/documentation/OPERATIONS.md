# Terminal operations

With a [management server](../../../src/server/README.md) configured, deployment and management use
its live device roster by default. `./micros devices` lists boards; one online board
is selected automatically, and several produce a terminal choice. Use `-d NAME`
or `-d DEVICE_ID` for scripts. The ESP connects outward to the server, so operators
need access to the server rather than each board's LAN. USB is an explicit onboarding
and recovery path.

For a new board or a base migration, start with [ONBOARDING](ONBOARDING.md).
The current protocol verifies the exact base ELF hash before service updates.
Incompatible or unidentifiable bases need physical migration before deployment.
Compatible ABI-5 graph-format-2 bases retain fixed-wiring support; remote wiring
changes require graph format 3.

## Prepare and review

```sh
./micros doctor -d feather
./micros config -d feather
./micros build -d feather --bundle build/release-review
./micros deploy -d feather --dry-run
./micros deploy -d feather
```

The preview reports setting/contract changes, slot placement, memory headroom,
the exact release ID and whole-application restart scope. Config-only changes
retain source versions. The package's image hash identifies exact linked bytes;
its build identity separately records source inputs and placement. Moving an
unchanged source release between slots does not require a version bump. Legacy
packages without that metadata retain exact-image version checks.

To build without a profile, pass `build --firmware BASE.elf --output DIRECTORY`;
add `--bundle DIRECTORY` to export the result before any deployment. Review builds
require the adjacent base sdkconfig when the application declares base settings.

## Promote and restore exact releases

```sh
./micros deploy -d feather --release build/release-review --dry-run
./micros deploy -d feather --release build/release-review
./micros history -d feather
./micros release -d feather build/saved-release --id RELEASE_PREFIX
./micros rollback -d feather --to RELEASE_PREFIX --dry-run
./micros rollback -d feather --to RELEASE_PREFIX
```

Compiled bundles include configuration and require the same base ELF identity.
They deploy without compiling source; overlays cannot alter them. Export uses a
new directory and writes a hashed completion manifest last. Import/deploy checks
all bytes before mutation. Bundles are integrity-checked, not a signed code
authority: application code remains trusted native code.

`rollback` without `--to` selects the previous confirmed local release. Explicit
release selection requires a unique ID/prefix in history and remains subject to
base compatibility and device health checks.

## Observe and recover

```sh
./micros status -d feather
./micros logs -d feather
./micros logs -d feather --follow
./micros stop -d feather
./micros recover -d feather
./micros reboot -d feather
```

Status distinguishes runtime liveness from application correctness, names services
when local receipts exist, and reports pending trials, physical recovery, reset
reason, stack headroom and update ownership. Live inspection does not require a
local ELF and remains available during another command's deployment. Local history
does not need network access.

Logs use byte cursors and a random boot identity. Identical text is preserved;
buffer loss and reboots produce explicit events. Follow mode reconnects after
transport interruptions. These are bounded volatile diagnostics, not durable
on-device logs. Older bases support a one-shot legacy tail only.

Each deployment writes a private attempt journal before mutation. After a killed
client, status explains its last saved phase and what the device reports now.
`stop_to_confirmation_seconds` measures the interval from requesting STOP through
health confirmation; it includes network and liveness-check time and is not a
measurement of the exact period in which service code was absent.

An authenticated update session reserves the expected selection across staging,
activation and recovery. Another updater receives a conflict; status/logs remain
available. The session expires after 60 seconds without an admitted mutation.
An abandoned staging session restores the unchanged selected graph if it is
stopped and no trial or physical recovery is pending. Pending trials retain their
independent firmware rollback policy. USB physical control remains authoritative.

`stop` is an intentional pause, unlike staging STOP: it stays stopped until
`recover` or reboot. All these operations affect the whole application. There is
no remote per-service restart. Base updates follow the separate
[base OTA procedure](BASE_OTA.md).

## Move to another checkout

```sh
./micros backup export /private/location/feather-backup
MICROS_STATE_DIR=/new/private/state ./micros backup import /private/location/feather-backup
MICROS_STATE_DIR=/new/private/state ./micros status -d feather
```

Private state backups contain credentials, paired firmware, receipts and physical
recovery artifacts. Store them privately; flash backups can contain Wi-Fi passwords.
Imports require empty state or an interrupted identical import, reject symlinks/path
traversal and verify files before writing. Device profiles are published last.
Local build caches are excluded. Exported release bundles are separate from private
device backups and do not contain the base ELF or management credentials by design.

## Maintain devices

```sh
./micros device list --json
./micros device refresh feather --port PORT
./micros device rename feather desk
./micros device remove desk
./micros device environment feather lab --overlay .micros/lab.toml
./micros deploy -d feather --environment lab --dry-run
./micros init feather --phase prepare --rotate-identity
```

Refresh reads the connected USB board's IP, checks its saved MAC and verifies HTTPS
before updating the address. DHCP reservations remain the simplest stable-address
choice. Wi-Fi commands prefer a saved serial port when available, then verify MAC.
Removing a profile archives its private files. Rotation prepares a new identity;
complete the explicit flash/connect migration phases to install it. Doctor reports
certificate expiry before it becomes a connection outage.

Named environments copy a validated tunable overlay into the private profile.
They are selected only by an explicit `--environment NAME`; deployment prints
the selection and the resolved setting diff. No last-used environment is applied
silently. Compiled release bundles already contain their selected configuration.

Application/device commands accept `--json`. Results use stdout; structured errors
and progress use stderr. HTTP errors distinguish authorization, conflicts, oversized
requests and busy devices. An unknown deployment outcome is not permission to retry
activation blindly: inspect status first. Independent device deployments use separate
locks; profile edits, backups and physical onboarding serialize workspace changes.

## Bound local package storage

```sh
./micros gc --keep 20 --dry-run
./micros gc --keep 20
```

Cleanup checks every saved active device and refuses to proceed if one is
unreachable or updating. It protects the current release, the last `--keep` unique
releases in each history (including archived pairings), and unresolved deployment
attempts. Older package bytes can be removed; version identities and audit history
remain so pruning cannot allow a changed service to reuse an old version.
Interrupted cleanup resumes safely. Legacy or damaged artifacts are skipped for
manual review.

Export any older release you want to keep before cleanup. A pruned local release
requires an exported bundle or private backup to deploy again. This command does
not remove build caches, credentials, base firmware or physical flash backups.
