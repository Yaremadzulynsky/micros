---
title: CLI
hide:
  - toc
---

<span class="docs-editorial"></span>

Reference · CLI
{: .arch-eyebrow}

# CLI

Use the help from your checkout for accepted commands and flags:

```sh
./micros --help
./micros deploy --help
```

An application's `./micros` launcher selects its unit. From the SDK, source
build/deploy commands need `--project UNIT.toml`; use `./micros sdk COMMAND …`
inside an application for explicit SDK commands. `-d NAME` selects a device;
use its hardware ID when working offline. See [Quickstart](get-started.md).

## 01 · Common commands {#common-commands}

| Task | Command | Details |
| --- | --- | --- |
| Validate the unit offline | `./micros compose` | [Declarations](declaration-authoring.md) |
| Generate service interfaces | `./micros generate` | [Write a service](write-a-service.md) |
| Inspect declared pins | `./micros pins` | Add `--all` or `--pin N` |
| Preview deployment | `./micros plan -d NAME` | [Deploy and update](deploy-an-application.md) |
| Inspect status/logs | `./micros status -d NAME`, `./micros logs -d NAME --follow` | [Shell](interactive-shell.md) |
| Diagnose connection/base compatibility | `./micros doctor -d NAME` | Reads tools, connection, and base identity |
| Inspect confirmed releases | `./micros history -d NAME` | [Rollback](deploy-an-application.md#restore-a-release) |
| Open console | `./micros server console` | [Server setup](run-management-server.md) |
| Enroll USB hardware | `./micros enroll` | [Board setup](set-up-an-esp32.md) |

`plan`/`deploy --dry-run` may contact devices and build packages. `compose` is
the offline check. Use `--json` only where the command's help lists it.

## 02 · Stop and restart {#stop-and-restart}

| Command | Effect |
| --- | --- |
| `./micros stop -d NAME` | Stop the whole application; intentional pause persists until recover or reboot. |
| `./micros recover -d NAME` | Resume the selected good application; refuses a pending trial. |
| `./micros restart INDEX -d NAME` | Restart one service on a supporting ESP32 base; select its zero-based status index. |
| `./micros reboot -d NAME` | Restart the device, interrupting management too. |

Individual restart requires `service_restart: 1` and an idle confirmed application,
without a pending trial, physical recovery, or deployment session. Peers retain
their instances; unsupported bases reject the command rather than restarting the
graph. After an uncertain response, inspect status/logs before issuing another
restart. See [failure boundaries](service-api.md#failure-and-memory-boundaries).

## 03 · Private backups {#private-backups}

For legacy SDK private state, run from the SDK root with the intended
`MICROS_STATE_DIR` (default `.micros`). Export profiles, identities, history, and
recovery artifacts to a new private directory. These may contain secrets:

```sh
./micros backup export /private/location/micros-backup
```

Stop the management server before importing into empty state:

```sh
MICROS_STATE_DIR=/new/private/state ./micros backup import /private/location/micros-backup
```

A private-state backup is separate from a compiled application release and from
a physical flash backup. Keep the server's selected state directory too; do not
assume a backup of legacy `.micros` covers separately stored operator/server state.

## 04 · Erase a controller {#erase-a-controller}

`./micros discover` can identify connected controllers; its ROM fallback resets
silent ESP devices. It does not write flash.

**`./micros erase` revokes enrollment on the configured console and clears firmware,
applications, Wi-Fi settings, and credentials. It makes no flash backup.** The
interactive flow asks for the hardware ID. Console access is required even if the
controller is not in its roster; unverified removal stops erasure. A failed erase
after revocation leaves the controller revoked. Factory ROM bootloaders remain;
the MKR flow also preserves its Arduino USB bootloader.

Use `./micros erase --help` for supported options, then [enroll again](set-up-an-esp32.md)
only when a fresh installation is intended. Normal application changes use deploy.

Advanced: [base OTA](update-the-base.md), [legacy composition](configuration-reference.md),
[diagnostic services](../../services/diagnostics/README.md), and
[contributor checks](contributing.md).
