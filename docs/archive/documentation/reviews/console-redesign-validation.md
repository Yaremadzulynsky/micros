# Management console redesign — September 14, 2026

The console follows the micros website’s typography, compact wordmark, white surfaces, quiet borders, and blue actions. The final workflow replaces the ten-section sidebar with Your boards and three board tasks: Board, Investigate, and Make a change. The default board screen shows application state and compact resource facts. Technical information opens in context.

## Feature preservation

| Capability | Final location |
| --- | --- |
| Fleet, search, presence/attention filters, counts, heap, last contact | Your boards |
| Board selection | Persistent header selector, including mobile |
| Service names, versions, running state, resident OS | Board overview |
| Uptime, platform, application confirmation, ABI, slots, reset reason, RSSI, refresh and JSON export | Board → Device details |
| Service results, steps, callbacks and timing | Board → Inspect services; expandable Execution timing |
| Publishers/subscribers, channel policy, backlog, depth, published/missed counts and age | Service details → Inspect service connections |
| RAM/PSRAM, reservations, stack watermarks, runtime/communication attribution, flash partitions and images | Board → Inspect memory & hardware; existing measurement semantics and accessible segment details retained |
| GPIO ownership, timer/handle budgets, resident base and heap history | Resource details → named disclosures |
| Logs, follow, loss/reboot markers | Investigate → Logs |
| Live waveform, capture/pause, service commands and gap reporting | Investigate → Live signals |
| Console operations and observed lifecycle events | Investigate → Activity |
| Network state, IP, RSSI, disconnect reasons and signal history | Investigate → Connection details; also linked from Device details |
| Application deployment and dry-run validation | Make a change → Deploy from CLI; copyable board-specific commands |
| Pause, recover and reboot | Make a change → Application controls, with confirmations |
| Display name, Wi-Fi primary/fallback profiles, saved-password preservation, reload/save | Make a change → Board settings; Wi-Fi opens on demand |
| Base hash, JSON export and enrollment revocation | Board settings → Base identity & management access |
| Enrollment and provisioning downloads | Your boards → Enroll a board |
| Token/ticket sign-in, secure sessions, sign-out | Existing authentication handlers retained |

## Validation

- All 68 server tests passed. The static-asset test was extended for the logo route, PNG content type/signature and existing CSP, and passed separately.
- Console JavaScript and updated browser regression scripts passed syntax checks. `git diff --check` passed.
- Exercised the actual console assets through the Codex in-app browser using the synthetic fixture `tests/server/console_design_fixture.py`.
- Verified three task entry points and all contextual destinations; expandable board facts, service timing, hardware ownership, reservations, resident base and heap history; refresh; logs read/follow; signal capture/pause and simulated command; activity and radio history.
- Verified synthetic exact-file release validation, review, confirmation/deployment and changed-file invalidation. Verified pause/recovery and immediate application-state changes.
- Verified lazy Wi-Fi loading, save, access details, draft-name preservation during polling and Wi-Fi save, offline actions, empty-board guidance, search/filter/no-match/clear behavior.
- Reviewed desktop at 1440×1000, mobile at 390×844 and fleet at 320×740. Tested mobile document widths matched their viewports. Resource detail fit inside the mobile viewport and supported Escape.
- No browser warnings or errors appeared in the final synthetic checks. Existing standalone browser scripts were updated to use the new navigation; their equivalent flows were exercised through the in-app browser.

## Pi deployment

Deployed the seven changed web assets and logo route in `server/console.py` to the existing tailpi management server. Used its existing Compose, Pi ownership and tunnel overrides. The deployed asset hashes match the local implementation. The server container is running with its existing loopback-only operator/device ports, private state and authentication configuration.

Public console: https://console.ydzulynsky.com/console/

A source archive and consistent SQLite snapshot were created at `/home/ydzulynsky/micros/backups/console-simplification-20260914T151117Z`. No active commands were present before the restart. For rollback, restore the source archive and rebuild with the same three Compose files; do not restore old registry state merely to revert the UI.

All five enrollments remain. Feather (four services) and Wroom (three services) reconnected after deployment. Their uptime increased; base identities and activation records remained unchanged. esp32-3b04, esp8266 and mkr were offline before and after the update. Their connectivity cannot be established from this UI deployment alone.

Verified the Pi origin over certificate-validated HTTPS: all changed assets match, the operator API still requires authentication, and the device listener rejects console routes. The public browser reached the existing Cloudflare sign-in. An authenticated public-browser session was unavailable, so live visual validation used the matching local assets rather than claiming a signed-in public check. No live-board deployment, reboot, Wi-Fi changes or enrollment changes were performed.

Screenshots and comparison evidence are under ignored `build/console-redesign/`; see `design-qa.md` for the visual iteration record.

## Resource styling follow-up

After the user selected the website’s resource illustration, RAM and flash adopted its blue/gray palette, slimmer bars and prominent available-memory readout. Every allocation category and interactive detail remains. Verified desktop/mobile rendering, service reservation and flash headroom details, Escape dismissal and mobile bounds; browser logs were clean. This change touches only `memory.js`, `flash.js` and `style.css`.

The refinement is deployed on tailpi. Backup: `/home/ydzulynsky/micros/backups/resource-style-20260914T153442Z`. Certificate-validated origin checks confirmed the changed asset hashes and existing operator/device boundaries. All five enrollments were retained; Feather and Wroom reconnected with unchanged base identities and activation records. The existing public Chrome session required Cloudflare sign-in after refresh, so public visual verification remains gated on that sign-in.

## Usability and CLI follow-up

The latest user direction moves application deployment to the CLI. The upload/review UI and its frontend state/handlers were removed; authenticated backend deployment APIs remain compatible. The board now links to a concise command guide with optional dry run. Board/task URLs support refresh, Back and bookmarks. Named resource legends open their details. Missing service names have an explanation, nonzero service results trigger attention, and Wi-Fi/connection failures offer recovery actions. Saved open networks display correctly.

The Pi package reader was behind its running ABI 7 applications. Updated the three existing package/admission reader files to the workspace versions, validated both application bank hashes against exact archived ELF/package records, then published the matching base/release artifacts and labels. Confirmed all seven service names and physical flash slots on Feather and Wroom. Their applications were not redeployed.

The 68 server tests and package parser/admission checks passed. Browser checks covered commands and copy, routes, resource detail focus/Escape, logs, live capture, Wi-Fi failure/retry and save, draft preservation, missing metadata, offline behavior and mobile layout. Deployed console hashes match; auth/device boundaries and all five enrollments remain. Backup: `/home/ydzulynsky/micros/backups/usability-sweep-20260914T155212Z`.

Current screenshots and numbered report: `build/console-redesign/usability-sweep/report.md`. Earlier deployment-form checks above document the superseded workflow; the current guide is CLI-based.
