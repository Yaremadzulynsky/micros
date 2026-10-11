# Deployment and remote-management usability review

**Date:** 2026-09-06  
**Status:** Original analysis retained below; the implementation follow-up records the fixes and validation.
**Scope:** Terminal-first micros, one board today and a small number of boards later. Keep direct HTTPS and USB recovery; no server broker, distributed IPC or fleet platform is required to address these findings.

## Implementation follow-up — 2026-09-06

The concrete workflow gaps have been addressed in themed commits. See
[terminal operations](../OPERATIONS.md) and [onboarding](../ONBOARDING.md) for the
current commands. The original findings below describe the starting point.

| Finding | Implemented correction | Verification |
| --- | --- | --- |
| 1. Base pairing | Full IDF-patched ELF hash, device MAC identity, ABI/graph limits; checks before preparation/STOP | Wrong/unknown-base unit checks; exact hash verified over HTTPS on the migrated Feather |
| 2. Fresh setup | `setup --esp32`; resumable `init` plan/prepare/flash/connect with automatic SDK activation | Prepared and migrated the real board; flashed only reviewed, hashed artifacts after a complete private flash backup |
| 3. Migration | Same-profile migration archives the prior pairing/history; old-base history stays separate; current docs corrected | ABI 5 board paired and four services confirmed; original 8 MiB flash retained |
| 4. Diagnosis | `doctor`; ELF-independent status/history/recover; live status during updates; per-device locks | Missing-ELF/writer-lock test; two device locks coexist; live doctor passes all checks |
| 5. Review | Setting/contract/placement diff, release ID, restart scope and code/data headroom | Config-diff unit check; live dry run preserved selection |
| 6. Placement/versioning | Separate source-input identity and exact linked image identity, with legacy exact-image fallback | Actual Xtensa relinking into different slots passed immutable-version checks |
| 7. Portable recovery | Verified private backup/import, pre-deploy release bundles, explicit rollback ID and base checks; resumable package retention with permanent version metadata | Backup roundtrip/corruption tests; compiled bundle promoted to the board as an exact no-op |
| 8. Health visibility | Explicit runtime-liveness wording, names from matching receipts, symbolic result categories, stack headroom, uptime/reset/recovery state | Live status shows four Running services; application correctness remains explicitly unverified |
| 9. Logs/outcomes | Byte cursors, boot identity, loss/reconnect events; durable per-attempt phase/outcome journal | Repeated-log/loss tests; live cursor logs; interrupted-transfer outcome test |
| 10. Connection/identity upkeep | Saved USB preference plus MAC check, authenticated USB address refresh, expiry diagnosis and explicit identity rotation | Existing Wi-Fi survived migration; live doctor verifies certificate and authenticated base |
| 11. Competing/abandoned updates | Device-owned session against expected selection, 60-second expiry and safe restart; intentional pause separate from staging STOP | Second client rejected without changing selection; abandoned STOP recovered the same four-service graph after 59.2 seconds as measured from the test's post-STOP observation |
| 12. Unified operations | Root stop/reboot, device administration JSON, structured errors, build-once/promote bundles, explicit named environments | CLI/host checks; live build/export/promote with no compilation during deployment and no activation for identical content |

Hardware evidence lives in ignored `build/usability-review/`: `first-deploy.json`,
`terminal/`, `hardware/management.json`, `release-deploy.json` and
`final-doctor.json`. The first STOP-to-confirmation interval was **16.769 seconds**,
including transfer and the liveness window. It is an upper window, not an exact
service-absence measurement. The terminal test passed four → three → four services
and no-op deployment. The final compiled-bundle promotion was also a no-op.
Intentional pause and recovery restored all four services. The full host suite
passed **27/27** checks; after adding retention, the expanded terminal suite
passed **33/33** tests, including interrupted cleanup and immutable version history.

The base's full ELF hash is
`bc7ce724f576ba7dccaaff45dd72dabf05e204aaf093a27939deac51495a77a4`.
The private original-flash backup hash is
`85f02b91f048733b319d9e019c6ee3ac8858075a3f5b12cf4f567cdbf50d286f`.
No credentials or firmware binaries are committed.

Deliberate limits remain: no functional readiness policy, durable on-device log
storage, zero-downtime staging, resumable chunk uploads, server broker or base OTA.
They were architectural follow-ups rather than prerequisites for the concrete
fixes above. Explicit `gc --dry-run` previews package retention; deletion requires
running `gc` without that flag. Current/recent/unresolved releases remain protected,
and version/audit metadata remains after package pruning. The real-workspace dry
run deleted nothing and preserved two legacy/unvalidated snapshots for manual review. Cold installation on a brand-new host, deliberate
certificate expiry/rotation, analog power cuts and additional physical boards
have not been hardware-qualified in this pass.

## Assessment

The daily deployment mechanism is stronger than the experience around it. It validates a whole graph, preserves exact packages, recognizes an identical running application, observes uncertain activation outcomes, and confirms device liveness. Those are foundations to retain.

The largest usability gap is that the operator still has to remember how the board, local ELF, credentials, application versions, build directories and rollback receipts relate. Several commands only work when this hidden context is intact. We should make that context discoverable and verifiable before adding more deployment features.

**Recommended order:** make compatibility explicit; make setup and diagnosis guided; make changes reviewable; make recovery independent of the original checkout; then improve coordination and transfer availability.

## Method and confidence

Reviewed the root CLI, build pipeline, private workspace, deployment state machine, HTTPS and USB clients, firmware management handlers, provisioning tools, documentation and relevant tests. Source references below identify the implementation supporting each finding.

Executed CLI probes with an isolated temporary `MICROS_STATE_DIR`, so existing profiles and credentials were untouched. Ran the `wifi_credentials`, `wifi_terminal` and `terminal_deployment` CTest checks: **3/3 passed**. No network requests to the board, serial connections, deployments or firmware changes were performed for this review.

Reproduced observations:

| Probe | Result | Usability implication |
| --- | --- | --- |
| `./micros --help` | Lists daily commands but not the shell wrapper's `setup` command | The first dependency-install step is not discoverable here |
| `./micros build --json` with empty state | Exit 1; requires a saved device | A local build has an implicit pairing prerequisite, unless explicit ELF/output options are used |
| `./micros status --json` with empty state | Exit 1; human error on stderr, no structured error | Automation must parse text for failure classification |
| `./micros device list --json` | Exit 2; unsupported option | Device administration does not share the application commands' JSON interface |
| Deploy with a nonexistent project and empty state | Reports missing device first | Prerequisites are discovered sequentially rather than summarized |

Raw probe output is in ignored `build/usability-review/cli-observations.json`. These tests establish CLI behavior, not current hardware readiness. Historical hardware evidence in the deployment/Wi-Fi guides predates the current generated IPC ABI; it must not be treated as verification that today's source has been deployed.

## What is already good

- One daily command builds, transfers, activates and waits for confirmation. A dry run makes no device changes, although it does generate local build/snapshot artifacts.
- Package and graph checks happen before STOP. Saved packages are hash-checked before reuse, and the selected graph is checked again before mutation.
- A lost activation response is observed through status rather than blindly retried. Interrupted staging attempts try to restore the prior selected graph when doing so is still appropriate.
- Successful rollback uses saved immutable packages, so it does not depend on recreating old source trees.
- Wi-Fi changes are tried before saving; failure or deadline restores previous settings. Password entry is hidden and Wi-Fi settings remain independent of application rollback.
- Pinned TLS identity, private local files and explicit Docker transport avoid insecure connectivity shortcuts.
- Shared deployment logic is separate from presentation, making improvements possible without replacing the state machine.

Sources: [deployment state machine](../../../../src/micros_tooling/deployment/deploy.py), [workspace](../../../../src/micros_tooling/storage/workspace.py), [Wi-Fi client](../../../../src/micros_tooling/communication/wifi.py), [management contract](../../../../src/firmware/management/README.md).

## Findings

Priority means recommended sequencing for this project, not a security severity score. **P0** blocks a dependable workflow; **P1** should follow soon; **P2** is useful once the basics are reliable.

### 1. P0 — The device cannot prove that we built against its base

**Observed in code:** registration checks the local ELF's slot symbols and saves its hash, but makes no device connection. HTTPS status returns selection, heap and service counters, without base identity, ABI, graph-format version or hardware identity. The builder checks a local symbol for ABI 5 support; it does not establish what is physically flashed.

**Consequence:** a correctly saved but incorrectly paired ELF can survive local preparation. Native-address or ABI rejection may then happen after services have been stopped. Even matching slot addresses do not independently prove that the base API is the intended one.

**Recommendation:** expose a bounded, authenticated identity/capability response containing a stable device identifier, base compatibility/build identifier, ABI revision, graph format and supported limits. Store the matching identifier with build artifacts and verify it before STOP. Use a reproducible identity design that avoids hashing a field into itself; do not simply promise that the in-memory ELF hash equals the flashed binary hash.

**Acceptance:** pairing the wrong base produces an actionable mismatch before service interruption; an older endpoint reports “compatibility cannot be verified” with a migration path. Certificate verification remains mandatory.

Sources: `Workspace.add_device`, `build_application` in [application.py](../../../../src/micros_tooling/build/application.py), `management_request` in [firmware main.c](../../../../src/firmware/platforms/esp32/runtime/main/main.c).

### 2. P0 — A fresh board still requires assembling the workflow manually

**Observed:** `./micros setup` installs Python packages only. ESP-IDF installation, credentials, base build, physical flash, initial service installation, Wi-Fi setup and device registration span separate scripts and documents. Registration needs an IP, certificate, token and ELF, with optional sdkconfig. Its success message suggests deployment is ready without validating reachability or pairing.

**Consequence:** the easiest route is asking someone who already remembers the correct sequence. Repeating the process for a second board risks reusing the default `build/private` identity and base accidentally.

**Recommendation:** one guided onboarding entry point, tentatively `micros init`, with explicit resumable stages: inspect tools → identify USB board → create/select that board's identity → build/select base → review and physically flash when requested → configure Wi-Fi → verify HTTPS identity and compatibility → save profile → install initial application. Preserve physical authorization for flashing; do not turn onboarding into an automatic destructive action.

Give each board a distinct identity by default. Let experienced users select existing artifacts rather than forcing rebuilds. Surface partial progress and the exact next step.

**Acceptance:** a fresh supported host and blank supported board can reach a confirmed application using one documented entry point; interruption at each stage can be resumed without guessing file paths or replacing an existing identity.

Sources: [wrapper](../../../../micros), [CLI](../../../../tools/micros.py), [provision.py](../../../../src/micros_tooling/deployment/provision.py), [BUILDING](../BUILDING.md), [DEPLOYING](../DEPLOYING.md), [WIFI](../WIFI.md).

### 3. P0 — The old-base-to-current-source migration is not a product workflow

The documentation explicitly says the saved Feather has not been migrated to the ABI 5/configuration branch. The physical migration crosses credentials, base layout, graph format, package rebuilds, initial service installation and profile replacement. Current device administration provides no migration/re-pair command; the guide asks for a new profile after base changes.

There is also conflicting guidance: the deployment introduction says ABI 4, while BUILDING, CONFIGURATION and source require revision 5. V1.md describes the original revision 3 milestone. Historical facts are useful, but their applicability needs to be obvious.

**Recommendation:** first publish a current compatibility matrix, then provide a reviewed USB migration plan with a private backup, selected new base, rebuilt application and final verified pairing. Keep service rollback history separated by base compatibility. Label the original V1 report historical rather than silently rewriting its measurements.

**Acceptance:** migration reports the old/new base identities, preserves recoverable old artifacts, verifies the new application, and leaves the ordinary deploy/status flow working. A service rollback never implies that it can undo a base flash.

Sources: [CONFIGURATION](../CONFIGURATION.md), [DEPLOYING](../DEPLOYING.md), [V1](../V1.md), `snapshot_packages` in [workspace.py](../../../../src/micros_tooling/storage/workspace.py).

### 4. P1 — Diagnosis depends on artifacts that diagnosis should not need

**Observed:** status, recover and even local history run through the paired-ELF hash check in the root CLI. Thus a missing or damaged local ELF blocks them before the command's actual work. Status/history also take the global workspace lock; a deployment holds it across building, transfer and confirmation. A second terminal's status command can therefore fail precisely when someone wants to inspect a running deployment. Logs are deliberately outside this lock.

The final error handler adds network advice to any `OSError`, including missing local files. USB request timeouts can be reported as an unsupported base, although a busy or interrupted serial link could also explain them.

**Recommendation:** decouple read-only inspection from build artifacts. Narrow locks to state mutations and the affected device. Add `micros doctor` with separate results for local dependencies, profile completeness, transport availability, TLS, authorization, firmware compatibility and application state. Report uncertainty instead of diagnosing every timeout as obsolete firmware.

**Acceptance:** status/logs work with credentials and address alone; history works offline without ELF or network; status remains available during deployment; missing Docker, local files, rejected tokens and unreachable devices each produce distinct next steps.

Sources: `main`/exception handling in [CLI](../../../../tools/micros.py), `Workspace.locked`, `Wifi.request`.

### 5. P1 — Deployment preview does not explain the intended change

**Observed:** human output lists current and requested service names/versions and the candidate bank. It does not show changes to settings, grants, subscriptions, schemas, slot placement or budgets. Config-only updates deliberately retain service versions, so both lists can look identical even when brightness or debounce changes. JSON exposes more planning data, but the human path does not summarize it.

**Recommendation:** a readable diff shared by `deploy --dry-run` and deployment: services added/removed/changed; old/new tunables; contract/resource changes; why relinking is required; slot and memory headroom; affected services; whole-graph downtime; recoverable prior release. Show the chosen device/address and target identity prominently. No routine extra confirmation is needed after the user explicitly runs deploy.

**Acceptance:** changing only brightness visibly reports `brightness: 7 → 12` and the restart scope. Removing a service identifies the removal and any resulting relinks. A preview can be tied to an exact artifact digest; deployment rechecks remote state rather than assuming the preview remains current.

Sources: deployment progress in [CLI](../../../../tools/micros.py), receipt fields in [workspace.py](../../../../src/micros_tooling/storage/workspace.py), [configuration semantics](../CONFIGURATION.md).

### 6. P1 — Automatic slot assignment can conflict with immutable service versions

**Code-derived risk, not reproduced on hardware:** enabled services are assigned fixed slots in declaration order. Removing an earlier service or reordering tables can move later services. The linker produces placement-dependent images, while version validation compares the manifest including image hash for the same name/version and base.

Therefore a service whose source and public contract are unchanged can be rejected as “different content; bump version” simply because its placement changed. The existing live-test narrative removes the final C++ service, which does not exercise this case. Contract changes can legitimately require a version change; placement alone needs a separate explanation.

**Recommendation:** define the distinction between service release identity and a compiled artifact for a particular base/slot. Consider preserving slot assignments across deployments, but handle removed/reintroduced services and fresh machines deterministically. Avoid making users maintain slot numbers in TOML as the first solution.

**Acceptance:** add a test that moves an otherwise unchanged service between slots. The outcome should either succeed under explicit artifact-variant rules or explain a deliberate placement policy; it should not misleadingly attribute the difference to source edits.

Sources: `load_project` slot assignment in [configuration.py](../../../../src/micros_tooling/config/configuration.py), [application builder](../../../../src/micros_tooling/build/application.py), `Workspace.check_versions`.

### 7. P1 — Recovery and identity are too dependent on one checkout

**Observed:** readable application identity is inferred from local receipts. Rollback requires a locally recorded current graph and a previous confirmed snapshot. There is no root command to select a named historical release, export/import the private deployment state, or rebuild a profile from a connected device. Losing `.micros/` loses the CLI's receipts, credentials and pairing even if the board still runs correctly.

**Important distinction:** firmware fallback does not disappear when laptop history is lost. What disappears is the convenient, named client workflow and ability to redeploy arbitrary saved releases. Merely selecting an older bank is not a substitute for retaining packages: staging may have overwritten it.

**Recommendation:** support deliberate private profile/release export and import, verification of backups, stable release identifiers and explicit `rollback --to RELEASE`. Separate portable application artifacts from device credentials. Export should disclose exactly what private material it contains; diagnostics should exclude it by default.

Also add history inspection and bounded storage retention. Snapshots accumulate, and current matching/version checks walk saved receipts/packages; cleanup must preserve active releases and intentional recovery points.

**Acceptance:** a second clean checkout can import a private backup, verify the board identity, identify the running release and restore a selected compatible release without the original source tree.

Sources: `snapshot`, `matching`, `rollback_target`, `check_versions` in [workspace.py](../../../../src/micros_tooling/storage/workspace.py).

### 8. P1 — “Healthy” means runtime liveness, not working application behavior

**Observed:** firmware waits five seconds, requires Running/no error and nonzero completed steps. The human status command labels Running/no-error services healthy. It prints numbered services and numeric results, not a per-service name mapping, reason text, readiness or recent reset cause. HTTPS status lacks uptime, Wi-Fi quality and stack headroom, although serial/runtime paths have some additional information.

**Consequence:** a logger decoding no useful messages or a color service never reacting to a button can still appear healthy. A stopped graph, failed graph and recovery situation collapse into broad wording.

**Recommendation:** first improve terminology and visibility: “running; startup liveness confirmed,” named services when identity is known, symbolic errors with numeric detail, selected/pending/fallback state and last failure. Add bounded application readiness/health reporting only after defining what a service must report and what should trigger rollback. Do not require a button press to qualify an otherwise valid update.

**Acceptance:** status distinguishes runtime running, trial pending, application readiness unknown, failed and physical recovery. A deliberately nonfunctional but running test service must not be presented as functionally verified.

Sources: `poll_health` and `management_request` in [firmware main.c](../../../../src/firmware/platforms/esp32/runtime/main/main.c), `running` in [deploy.py](../../../../src/micros_tooling/deployment/deploy.py), status rendering in [CLI](../../../../tools/micros.py).

### 9. P1 — Logs and interrupted operations need a durable explanation

**Observed:** logs are a bounded text tail; follow mode deduplicates by string overlap. Repeated identical text may disappear and fast output may be lost. A transport failure exits follow mode. Successful history is saved, but there is no durable per-attempt journal recording phase, target digest, last observed device state and recovery outcome. `DeploymentError.outcome` exists internally but is flattened into a human error at the CLI boundary.

**Recommendation:** persist a small deployment-attempt record before mutation and update it by phase. Status should reconcile an unresolved attempt without implying that an absent reply means failure. For logs, use a boot identifier and monotonically increasing cursor with explicit lost-record counts; add source/level filtering and reconnect behavior within bounded device memory.

**Acceptance:** terminate the client after STOP, midway through upload and after activation; the next status explains the known phase and safe next action. Repeated identical log records remain distinct, gaps are reported, and a reboot is distinguishable from an empty tail.

Sources: [deploy.py](../../../../src/micros_tooling/deployment/deploy.py), logs/exception paths in [CLI](../../../../tools/micros.py), log ring in [management.c](../../../../src/firmware/management/src/management.c).

### 10. P1 — Connection and credential maintenance are still manual

DHCP reservation is a reasonable current operating choice. The CLI saves an address and can update it manually or after USB Wi-Fi setup, but does not rediscover a moved device. Native versus Docker routing is another manual choice; Docker starts a container for each request and depends on a separately built image. Saved serial-port metadata is written during setup but not used by `select_port`; ambiguous adapters still require a port argument.

Development certificates expire after 365 days. Provisioning preserves an existing identity, and there is no expiry warning or guided rotation. Remote access can therefore stop working through an ordinary lifecycle event without a clear maintenance workflow.

**Recommendation:** doctor should explain native/Docker availability and certificate expiry early. Use saved board identity when assisting USB selection, not just a remembered path or vendor ID. Optional hostname/mDNS discovery can help later, but discovered addresses must still pass certificate and device-identity checks. Keep USB Wi-Fi setup as the simple reliable path; remote Wi-Fi replacement is not necessary yet.

**Acceptance:** expired/expiring identity, wrong address, wrong token, missing Docker and mismatched USB board have distinct messages. Reconnection never falls back to plaintext or accepts a newly discovered identity automatically.

Sources: [remote.py](../../../../src/micros_tooling/communication/remote.py), [provision.py](../../../../src/micros_tooling/deployment/provision.py), [wifi.py](../../../../src/micros_tooling/communication/wifi.py), [Wi-Fi guide](../WIFI.md).

### 11. P1/P2 — Multiple clients can race; transfer downtime remains operator-dependent

The current local lock and before-STOP selection check are useful, but do not reserve the board across STOP/upload/activate. Two computers can interleave updates. The expected activation digest prevents silently accepting substituted content; it does not prevent disruption or guarantee a useful recovery result for both clients.

Services stop before any images transfer. If the client vanishes after STOP, a reachable client must recover the graph or the board must reboot; there is no visible deployment-session deadline that automatically restores service after an abandoned staging session. Slow connections extend downtime. Uploads are complete-request transfers rather than resumable chunks.

**Recommendation:** introduce a bounded device-owned deployment session/lease before encouraging use from multiple computers. Bind mutations to its expected selection and target identity, report owner/session state, and define expiry behavior. Then evaluate staging while services run, changed-image transfer or resumable upload only against measured RAM/flash/runtime constraints. Those are architectural changes, not CLI polish.

**Acceptance:** two clients produce one identifiable owner and an actionable conflict. Killing the owner after STOP leads to a defined autonomous recovery outcome. Any lease recovery must preserve the selected good graph and remain subordinate to pending activation/physical recovery rules.

Sources: [deploy.py](../../../../src/micros_tooling/deployment/deploy.py), `MICROS_MANAGEMENT_IMAGE` handling in [firmware main.c](../../../../src/firmware/platforms/esp32/runtime/main/main.c), [management contract](../../../../src/firmware/management/README.md).

### 12. P2 — Automation and advanced operations fall outside the simple CLI

`--json` covers successful application output but not a uniform structured error contract. Device commands lack it. The public root CLI has no reboot/stop commands even though the remote endpoint and lower-level script provide them; remote per-service start/stop/restart is not implemented simply because the host CLI supports those operations.

Ordinary deploy always builds from source. There is no root path to promote an already-reviewed release artifact to another compatible board, no selected historical rollback target, and no profile rename/remove or saved environment-overlay association. Overlay paths must be supplied again each time. The global workspace lock also serializes independent boards.

**Recommendation:** keep one primary CLI with consistent device selection and error envelopes (`code`, `phase`, `outcome`, `retryable`, next action). Add artifact deployment and explicit release selection before CI/fleet orchestration. Promote existing whole-device management operations with clear scope; do not promise unsupported per-service remote lifecycle control. Keep the last-used overlay from becoming a silent default: make environment selection explicit and visible.

**Acceptance:** scripts do not scrape human text; a reviewed bundle deploys without a compiler; all routine operations reuse the saved profile. Failures remain nonzero and machine-readable without leaking credentials.

Sources: [root CLI](../../../../tools/micros.py), [lower-level remote CLI](../../../../tools/cli/micros_remote.py), [workspace.py](../../../../src/micros_tooling/storage/workspace.py).

## Proposed milestones

These are reviewable scopes, not time estimates. Each should land as themed commits and finish with its acceptance evidence.

| Milestone | Deliverable | Completion demonstration |
| --- | --- | --- |
| D0 — Know what is deployed | Identity/capability protocol, pre-STOP compatibility checks, current compatibility documentation | Wrong-base pairing rejected without interruption; old firmware receives an explicit unsupported-verification result |
| D1 — Get a board ready | Guided resumable USB onboarding/migration and doctor; inspection independent of ELF; narrower locks | Clean host/board setup, interrupted setup resume, status during deployment and with missing build artifacts |
| D2 — Understand an update | Human diff, clear target/environment, memory and restart scope, placement/version identity decision | Config-only diff, service removal/reordering, capacity rejection and repeat no-op deployment |
| D3 — Recover from another checkout | Portable private profile backup, immutable release bundles, named rollback and attempt journal | Fresh checkout imports backup and recovers three interruption scenarios with exact compatible packages |
| D4 — Operate remotely with confidence | Named status/reasons, bounded log cursors/reconnect, JSON error contract, expiry diagnostics, unified existing operations | Reboot/log loss/repetition and connection failures yield understandable, scriptable outcomes |
| D5 — Coordinate updates | Device session ownership/expiry; measure and then reduce downtime if needed | Competing clients and abandoned staging have deterministic recovery; report measured service interruption |

D1's client-only diagnosis improvements can begin before a firmware migration, but a fully verified onboarding finish depends on D0. D3 release promotion depends on D2's identity decision. D5 should precede routinely deploying from multiple computers; a central server is not needed to implement it.

## What I would deliberately defer

- A broker/server, Tailscale on the MCU, cross-network service IPC and a fleet dashboard.
- Kernel OTA, which is outside the current physical-base-update policy.
- Remote Wi-Fi switching, until there is a clear need beyond the working USB path.
- Live per-service config reload and zero-downtime updates until the review/diff/recovery workflow is dependable.
- A broad service health-policy system before status accurately describes the liveness evidence already available.

The ESP32 memory budget is constrained, and the published headroom belongs to a particular historical build. Measure the current base before accepting new protocol/session/log allocations. Prefer compact metadata and host-side presentation to large device-side tooling.

## Discussion points

1. Should the next deliverable be **D0 plus the client-only parts of doctor**, followed by a guided migration of the Feather? This is my recommendation.
2. Should an application release be a named, immutable bundle that we can build once, review and deploy repeatedly? I recommend yes, while keeping `micros deploy` as the fast source-to-device path.
3. Should version numbers describe service source/contracts independently of base/slot compilation? I recommend deciding this before adding more automated placement or release promotion.
4. Is the near-term operating target one developer with a few boards, or multiple independent operators? The answer determines how soon D5 is required; it does not require designing a fleet platform now.

The next success criterion should be simple: someone who did not build the firmware can identify the board, understand the proposed update, deploy it and recover from an interruption without knowing our directory history.
