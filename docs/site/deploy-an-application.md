---
title: Deploy and update
hide:
  - toc
---

<span class="docs-editorial"></span>

Use · Deploy and update
{: .arch-eyebrow}

# Deploy and update

From your application directory, deploy one unit to its enrolled board. Application
updates retain the resident base; kernel/platform changes use [base OTA](update-the-base.md).
{: .arch-intro}

## 01 · Preview and deploy {#preview-and-deploy}

Replace `NAME` with the enrolled name or hardware ID. Its unit must declare the
same hardware ID. See [enrollment](set-up-an-esp32.md) for the first installation.

```sh
./micros plan -d NAME
./micros deploy -d NAME
./micros status -d NAME
./micros logs -d NAME
```

Enrollment already deploys the simulated climate starter unless you selected
`--no-starter`. Use this workflow for subsequent changes. Check your selected services
are Running with no pending trial. For the unchanged climate starter, expect
three services and verify `Simulated climate` log lines:
the default fan turns on at 28°C and off at 24°C. These are generated readings
and a simulated fan decision, not a physical sensor or actuator test.

From the SDK checkout, add
`--project PATH/TO/UNIT.toml` to plan/deploy. `deploy --dry-run` is also available;
ESP32 `plan` uses that preview path. Other platforms use their own dry-run behavior.
Planning may contact the board/server and build packages; `compose` stays offline.

The plan reports changes and restart scope. Identical running content is a no-op;
identical stopped content can restart without uploading. `--force` requests a full
activation. Content hashes identify releases; a version bump is not required.
A preview is not a saved executable plan: a later source deploy checks current inputs.

For a changed ESP32 application, deployment transfers all prepared service images
and the complete configuration to the candidate bank, even when only one service
will reload. Transfer scope and restart scope are separate.

## 02 · What restarts {#what-restarts}

On ESP32 bases advertising `selective_deploy`, compatible updates reload changed
services and preserve unchanged peers' instances, memory, handles, and subscriptions.
Peers pause briefly at hook boundaries for flash writes and the mapping switch.
Changes to membership, ordering, shared channels, wiring, or slot layout can require
whole-application activation. Unsupported bases and forced deployments use the
whole-application path. Firmware checks compatibility at activation.

| Phase | Whole-application path |
| --- | --- |
| Validate | Current application runs while compatibility and capacity are checked. |
| Stage | Application pauses; resident management receives the candidate. |
| Trial | Candidate runs; the runtime checks liveness and progress. |
| Confirm | Candidate becomes the recorded good selection. |

For ESP32, the liveness window is five seconds. It does not verify sensor accuracy
or physical outputs. A hung native worker can still require device recovery;
selective deployment is not memory isolation or uninterrupted real-time execution.

## 03 · Resolve a failed update {#resolve-a-failed-update}

| Result | Next action |
| --- | --- |
| Rejected before staging | Fix the reported base, contract, or resource mismatch; the current graph was not stopped. |
| Transfer interrupted | Reconnect and inspect status; the client/session recovery can resume the good graph when safe. |
| Candidate startup fails | Inspect the recorded selection and failure; trial recovery can restore the good graph. |
| Activation reply lost | Treat the outcome as unknown until status identifies the selected application. |

The ESP32 staging lease is 60 seconds and candidate boot allowance is two attempts.
Neither abandoned-session recovery nor `recover` overrides a pending trial or
physical recovery state. Without a usable good graph, recovery needs attention.
Intentional `stop` is different from abandoned staging; see [CLI controls](cli.md#stop-and-restart).

## 04 · Keep a compiled release {#keep-a-compiled-release}

A release preserves compiled packages rather than mutable source paths:

```sh
./micros build -d NAME --bundle build/release-review
./micros deploy -d NAME --release build/release-review --dry-run
./micros deploy -d NAME --release build/release-review
```

Use a new bundle directory. The bundle requires a compatible exact base; an overlay
cannot change it. For server-backed source builds, the server must have the board's
matching base ELF and adjacent `sdkconfig`. Enrollment/preparation retains the base;
for an existing build, publish it with:

```sh
./micros server publish-base --firmware PATH/TO/micros_runtime.elf
```

Base artifacts can contain secrets. See [packages and compatibility](packages-and-storage.md).

## 05 · Restore a release {#restore-a-release}

```sh
./micros history -d NAME
./micros rollback -d NAME --to RELEASE_ID --dry-run
./micros rollback -d NAME --to RELEASE_ID
```

Use a full ID or unique prefix. Without `--to`, rollback selects the previous
confirmed release available to the workflow. It needs the retained packages and
compatible base, then runs ordinary deployment checks. The two device banks are
reused; they are not an unlimited history. [Private backups](cli.md#private-backups)
and compiled releases serve different recovery purposes.
