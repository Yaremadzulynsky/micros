# Deploying from the terminal

With a [management server](../../../src/server/README.md) configured, deployment and management use
its live device roster by default. `./micros devices` lists boards; one online board
is selected automatically, and several produce a terminal choice. Use `-d NAME`
or `-d DEVICE_ID` for scripts. The ESP connects outward to the server, so operators
need access to the server rather than each board's LAN. USB is an explicit onboarding
and recovery path.

The selected board’s `units/<device_id>.toml` defines the daily loop. The filename uses its 12 lowercase MAC digits without separators. Each unit owns its service selection, settings, channels and hardware wiring. This configuration revision requires the identity-reporting ABI 5 base. Use [guided onboarding/migration](ONBOARDING.md), then [current terminal operations](OPERATIONS.md) for release bundles, diagnosis and recovery.

```sh
./micros build             # Compile and validate locally; no device connection
./micros deploy --dry-run  # Build, check the device and preview; no device changes
./micros deploy            # Build → transfer → activate → confirm health
./micros status
./micros logs
./micros logs --follow     # Ctrl-C to finish; may stay open during deployment
./micros rollback          # Restore the previous locally recorded application
```

`deploy` checks all packages, resource budgets, channel compatibility and slot addresses before stopping services. It prints progress and waits for the device's health confirmation. An identical running application needs no flash writes. `--force` explicitly runs another activation of the same content. There is brief service downtime during staging.

Change source and bump the changed service's `version` under `[services.NAME]` in the unit file. Change tunables in the unit file without bumping executable versions, then run `./micros deploy`. Source and contract identity remain immutable for a name/version; configuration, grants and board bindings may differ per deployment. Placement or wiring changes can relink the same source version, while the image hash still identifies exact executable bytes. The builder reuses unchanged executables and records compiler output in `.micros/build/DEVICE/SERVICE/build.log`. All changes use the existing whole-graph activation and rollback flow.

## First-time setup

Prefer `./micros setup --esp32` followed by `./micros init NAME`; see [ONBOARDING](ONBOARDING.md). Manual artifact registration remains available below.

Install the ESP32 toolchain using [BUILDING.md](BUILDING.md), then set up Python dependencies:

```sh
./micros setup
```

Configure the flashed device with `./micros wifi setup`; [Wi-Fi setup](WIFI.md) also works when the network is unavailable. The device must already have a network-enabled micros base and physically provisioned certificate/token; see [provisioning](../../../src/firmware/management/README.md). Register it once:

```sh
./micros device add feather \
  --host 192.168.0.15 \
  --certificate build/private/servercert.pem \
  --token-file build/private/management.token \
  --firmware build/esp32-runtime/micros_runtime.elf
./micros device list
./micros device use feather
```

The first device becomes the default. Use `-d NAME` on any application command to select another. Update a DHCP address with `./micros device address feather NEW_IP`. A DHCP reservation keeps this address stable; the client does not configure the router.

Registration copies the client certificate, bearer token, base ELF and adjacent `sdkconfig` into ignored `.micros/devices/NAME/`, with private file permissions. Use `--sdkconfig PATH` if the configuration lives elsewhere. The base ELF copy prevents a later local base build from silently changing service link addresses. Keep `.micros/` backed up privately if you need its credentials and rollback history. The client uses the certificate and bearer token. Treat the paired ELF/configuration as private too: the base ELF embeds management credentials, and older configurations may contain Wi-Fi passwords.

The ELF and configuration must belong to the base actually flashed on the board. Server-backed deployment retrieves these by the authenticated live base hash from the server, verifies their hashes and caches them locally. The operator needs server credentials, not a local device pairing backup. Current firmware reports the original base ELF SHA-256, hardware identity, ABI and graph format over authenticated HTTPS. Deployment verifies the paired ELF before preparing an update and refuses older firmware that cannot report identity. The device also checks native image addresses at activation. Changing the base uses the explicit physical `micros init` phases, which archive the prior pairing and history; `deploy` replaces services only.

## Application file

[micros.toml](../../../config/micros.toml) selects services, settings and shared channel contracts. The same file groups each service’s build sources, capabilities and typed configuration definition with its selected settings. Actual protobuf message definitions live under `protos/`. See [configuration strategy](CONFIGURATION.md).

The builder assigns slots, reads arena/stack requirements from native descriptors and computes hashes. Generated `resolved.json`, headers, images and packages live in the build output. `required_sdkconfig` checks the paired base; the current pixel driver requires 160 MHz without dynamic scaling.

Network deployment selects `units/<device_id>.toml` using the selected device’s saved identity and checks it against the authenticated live board before building. A missing unit file is an error; there is no fallback to the root template. `--project PATH` must still name a complete unit file for that same device. Use `--overlay PATH` to override only tunable values. Hardware bindings come from the unit file; a conflicting `--board` override is rejected. Removing or disabling a service changes the next selected graph and can shift slot assignments. Whole-graph admission still applies.

## History and recovery

The client saves exact packages and both bank digests before stopping the board. Successful deployments enter `.micros/devices/NAME/history.json`; `./micros history` shows them; `rollback --to RELEASE_PREFIX` selects an explicit compatible release. Status also reconciles a saved snapshot when its graph is selected, no trial is pending and every service is running, covering a client exit after successful activation. Application names and versions shown by the client come from matching local receipts, not from the firmware. An unknown graph is labelled as unrecorded.

`rollback --dry-run` previews the previous confirmed local application. `rollback` redeploys its immutable packages through the normal health check, even when an earlier bank has been overwritten. It requires this computer's history, including a recorded current application. Run `deploy` once on an already-running matching application to establish that baseline. A successful rollback becomes the newest history entry; another rollback returns to the preceding application.

If a transfer fails, the client tries to restart the previously selected good graph, only when the same graph remains selected and no trial is pending. It reports whether recovery was verified. If an activation response is lost, it observes status rather than blindly sending activation again. For an unknown result:

```sh
./micros status
./micros logs
./micros recover
```

`recover` restarts the selected good graph and refuses to interfere with a pending trial. A killed client or unreachable device cannot perform immediate recovery. Reconnect and inspect status first. The firmware's trial/reboot fallback remains in effect independently of this client.

Independent devices use separate local update locks. The firmware reserves a deployment session against the expected selection across STOP, upload and activation. Competing clients receive a conflict; abandoned staging restores the unchanged selected graph after the 60-second session deadline when no trial or physical recovery is pending.

Logs use a bounded byte cursor and boot identity. Repeated text remains distinct; lost bytes and reboots are reported explicitly. Following reconnects after transient transport failures. This is not durable storage. All application commands accept `--json`; progress and errors use stderr, success data uses stdout, and failures exit nonzero.

## Connectivity on this Mac

The existing environment has previously reached the Feather through Docker while native Python reported `No route to host`. The saved local `feather` profile uses the explicit Docker transport. For other machines, native HTTPS is the default. Select the transport with:

```sh
./micros device transport feather native
./micros device transport feather docker
```

Docker transport requires a running local Docker engine and the existing `micros-linux-tools:v1` image. To build it without sending private workspace files as Docker context:

```sh
mkdir -p build/deploy-docker/tools
cp tools/release/Dockerfile.linux build/deploy-docker/Dockerfile
cp tools/requirements-dev.txt build/deploy-docker/tools/requirements-dev.txt
docker build -t micros-linux-tools:v1 build/deploy-docker
```

The client runs one short-lived container per request with host networking. The certificate and token travel over process stdin; they are not command arguments, environment variables or mounted workspace files. Both transports verify the saved device certificate and use authenticated HTTPS. Docker transport is intended for a local engine, not a remote Docker context.

If neither transport connects, check board power, Wi-Fi, the saved IP and host LAN access. An HTTP 401 means the saved token was rejected. A certificate error means the saved device identity did not verify. USB recovery and physical provisioning remain available through the existing tools.

## Validation

The host suite includes `terminal_deployment`: tests cover dry-run behavior, confirmation/history, immutable versions, saved-package corruption, pending trials, competing selections, lost activation replies and interrupted-transfer recovery. Run it with:

```sh
ctest --test-dir build/host -R terminal_deployment --output-on-failure
```

For an explicit live OTA test on the provisioned Feather:

```sh
build/python/bin/python tests/hardware/terminal.py --device feather
```

This records the four-service application, temporarily deploys it without the C++ service, rolls back to all four services, and verifies an identical deployment performs no activation. Button and color services remain in both graphs. Evidence is saved under `build/terminal-hardware`. An unknown network outcome stops the test for inspection rather than triggering an unconditional restore.

Verified on the physical Feather on 2026-09-06: the dry run preserved activation sequence 65; the three-service OTA update confirmed bank 1 at sequence 68; rollback restored the original four-service graph in bank 0 at sequence 71. The final identical deployment left sequence 71 unchanged. Status, logs and local history commands also succeeded. Evidence is in `build/terminal-hardware/`. The base firmware SHA-256 remained `c50d8ba4475b790762282a369e637fdf2fcccc8fe078e26e1ad408b0b291758c`; no base flashing or credential changes were performed.

## Per-unit deployment

```sh
./micros deploy -d feather
./micros deploy -d esp32-no-controls
```

These select `units/e89f6d30e1a8.toml` (button and colors, 8 MiB Feather)
and `units/b0a732c8082c.toml` (hello-world, 4 MiB ESP32 with no GPIO), respectively.
Edit only the relevant unit file to select services (`enabled = false` or remove
that service table), change settings, or change its wiring. Source and schema
paths are relative to the unit file, so repository paths start with `../`.
Server credentials remain private in `.micros/server`. Exact base artifacts are stored privately on the server and cached in `.micros/artifacts/bases/HASH/`.

For a new board, create `units/<device_id>.toml` with its `[unit]`, `[board]`,
service and channel tables, then prepare/pair it with
`./micros init NAME --project units/<device_id>.toml` using the normal USB phases.
The prepared unit identity is checked against the USB MAC before flashing.
Network deploy updates the complete service graph against that board’s exact
server-stored base ELF and verifies base compatibility. Base firmware replacement still
requires USB provisioning. Explicit `--release` deployments and rollback use their
existing immutable packages and base compatibility checks.

## Server artifact retention

With a configured management server, `init --phase prepare` publishes the exact
base ELF and its adjacent `sdkconfig`. Existing builds can be published with
`./micros server publish-base --firmware PATH/firmware.elf`. Uploading artifacts
does not flash a board. `./micros server publish-history NAME` migrates retained
local deployment packages and confirmation history after their bases are present.

Before activation, the CLI archives the service packages, receipt, authored unit
configuration/overlay and resolved recipe. Confirmation is recorded after health
checks pass. A failed confirmation upload leaves an archived candidate, without
claiming success. Deployment and rollback hydrate server release history before
selection. A dry-run fetches and validates artifacts but does not upload a new
release or change a device. Retained packages are immutable. Distinct authored/resolved configuration variants
for the same package bytes are also retained by checksum.
