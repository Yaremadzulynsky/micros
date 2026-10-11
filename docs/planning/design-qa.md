# Console design QA — September 14, 2026

final result: passed

## Reference and scope

- Source visual truth: `build/console-redesign/01-website.png`, captured from the existing micros website at `http://127.0.0.1:5173/`, and `src/website/src/styles.css`.
- Implementation: `build/console-redesign/04-fleet-after.png`, `05-overview-after.png`, `resources.png`, `deploy.png`, `login.png`, `mobile-overview.png`, `mobile-navigation.png`, `mobile-memory-detail.png`, `mobile-settings.png`, and `small-mobile-fleet.png`.
- Desktop source and final overview screenshots: 1440×1000 pixels / CSS viewport. Mobile: 390×844 and 320×740. Laptop also checked at 1280×720. No density scaling was needed for the final source/overview comparison.
- State: website introduction versus signed-in operational console with explicitly synthetic devices. This is a shared-style redesign, not a pixel-for-pixel copy of the marketing layout.
- Full-view comparison: source website, redesigned overview and mobile overview were inspected together in the same comparison input. Initial console screenshots `02-fleet-before.png` and `03-board-before.png` establish the previous style and navigation.
- The final normal-viewport images show typography, logo and controls at readable size; separate region crops were unnecessary. Earlier full-page captures with stitching artifacts were rejected and relevant files replaced with normal-viewport captures.

## Fidelity surfaces

- **Typography:** same Arial/Helvetica system as the website, neutral ink, restrained optical weight, small uppercase section labels. Operational headings are intentionally smaller than marketing headlines. Device names wrap or truncate in constrained navigation rather than expanding the page.
- **Spacing/layout:** white canvas, quiet separators, modest rounded panels, and generous but consistent spacing. Board context precedes section content. Three task entry points replace the ten-section sidebar; technical tools open in context. Resource summaries precede detailed tables. Mobile navigation retains all tasks, contextual tools, search and sign-out.
- **Colors/tokens:** neutral `#17191d` ink, `#626c79` secondary text, `#dce2e9` borders and `#075edb` actions align with website tokens. Pale blue anchors the resident OS. Semantic status colors are retained. Resource allocations now use the website’s restrained blue/gray palette, with names and interactive details identifying each service.
- **Asset fidelity:** uses the exact existing compact micros raster wordmark at 108px desktop / 96px mobile, preserving proportions. No invented logo or decorative stock imagery.
- **Copy/content:** operational section descriptions and explicit action consequences. The overview distinguishes resident management from application services. Memory and flash retain measured/reserved/unknown qualifications. Offline rows say “last running.”

## Comparison and correction history

1. Baseline: separate green palette, ten equal-weight tabs, no service summary in Overview, and mobile-hidden board search/sign-out. Replaced with shared website tokens, grouped sidebar, application/OS summary and responsive drawer.
2. Laptop inspection: navigation groups consumed too much vertical room at 720px height. Reduced desktop navigation spacing; all ten sections remain available in the sidebar’s own scroll area. Evidence: `laptop-overview.png` and final overview.
3. Functional QA: resource auto-refresh could interrupt focused details; status refresh could discard form/file state. Refresh now preserves focused controls/details and avoids rebuilding editable sections. Verified RAM popup, draft name across refresh/polling, and file review state.
4. Lifecycle QA: preserving focused action controls initially left the overview stale after recovery. Forced the post-operation render, then retested pause/recovery: service state changes immediately from Running to Stopped and back.
5. Final refinement: explicit current deployment step, primary deployment action after validation, disabled uploads during validation, specific pause/recover/reboot confirmations, and explicit capture-pause message on command submission. Rechecked release review and lifecycle flows after changes.

## Verification and remaining limits

All original capabilities and their new contextual destinations were exercised; no actionable P0/P1/P2 findings remain. Mobile document overflow was absent in every tested section. RAM details fit within the viewport and support Escape. Inputs retain drafts during refresh. Browser console had no errors/warnings. The 68 server tests passed, with JavaScript syntax and diff checks also passing.

See `docs/archive/documentation/reviews/console-redesign-validation.md` for the complete feature-preservation map and tested flow steps. The final assets were deployed to the Pi and verified by hashes and certificate-validated HTTPS checks. Two live boards reconnected with unchanged base identities and activation records. The public browser required Cloudflare sign-in; no authenticated public visual check is claimed. Full assistive-technology certification was not performed.

## Workflow simplification after user feedback

The first pass matched the website visually but still exposed too many choices. The final pass removes the sidebar, duplicate context headings, overview metrics and always-visible technical tables. Board, Investigate and Make a change are the three primary tasks. Device facts, timing, hardware budgets, Wi-Fi settings and access controls open in named disclosures. RAM/flash and service connections retain dedicated detail screens with clear return paths.

The website reference, first-pass overview and final overview were inspected together at 1440×1000. The final header/content alignment follows the website. The application and resource summary fit in one desktop view; mobile retains a straightforward vertical flow without a navigation drawer.

Evidence in `build/console-redesign/simplified/`: `01-fleet-before.png`, `02-board-before.png`, `03-fleet-after.png`, `04-board-after.png`, `05-deploy-review.png`, `06-mobile-settings.png`, `07-mobile-board.png`, `08-mobile-resources.png`, and `09-small-mobile-fleet.png`. Normal viewport captures were used.

Final functional checks covered all new routes, lazy disclosure loading, exact-file review invalidation, settings drafts, simulated controls, offline/empty states and 390/320px overflow. The complete server suite passed (68 tests), and the extended asset-route check passed. No actionable findings remain from this scoped visual and interaction review.

## Resource palette refinement — September 14, 2026

final result: passed

Source: `build/console-redesign/resource-style/website-reference.png` (user-provided website resource illustration, 2290×1092 pixels). Compared together with `resources-desktop.png` (1440×1000 CSS-pixel viewport) in the same browser-tool output. This is a visual-language match to the illustrated component, not a duplicate of its example values or marketing-page layout; measurements and all original allocation categories remain intact. The source is a cropped high-density image. Relative component hierarchy, colors and bar proportions were compared without claiming pixel-exact placement.

- Typography: Arial/Helvetica remains; muted blue-gray labels and a prominent available-memory readout reproduce the reference hierarchy.
- Layout: slim 18px visual bars retain 34px pointer/focus targets. Pool separators, wrapping legends and quiet borders match the reference treatment.
- Colors: all services share `#4481cd`, system allocations use blue-gray tones, free memory uses solid `#e9eff6`, and reserved flash headroom retains fine hatching. The old coral/purple/gold palette is removed.
- Assets: no new raster asset is required for these functional resource charts. The existing wordmark remains unchanged.
- Content: used/total/free measurements, per-service RAM reservations, stack peaks, communication/runtime attribution, flash images, headroom and unknown/disabled states remain available.

The initial mobile check revealed that the global button minimum height made the visual bars thicker than intended. An explicit 34px target height restored the intended 18px bar, followed by the final desktop/reference comparison. The basic PSRAM legend was aligned with its muted usage segment.

Focused interaction evidence: `flash-detail.png`, `resources-mobile-detail.png`, and `resources-mobile.png` in the same evidence directory. Service details and Escape dismissal were verified. At 390px, document width was 390px and the RAM detail remained within x=41–349px. Browser logs contained no errors/warnings. JavaScript syntax and diff checks passed. No actionable P0/P1/P2 findings remain for this scoped refinement.


## September 14 · usability sweep and CLI deployment

Replaced the upload workflow with the website-style one-command guide. Checked desktop and 390px mobile; command copy, route restoration, named legend access and Escape, logs/capture, Wi-Fi failure recovery, saved open-network state, and missing labels. Evidence and limitations are recorded in `build/console-redesign/usability-sweep/report.md`. The Pi now has verified names and flash-slot metadata for its running Feather/Wroom applications.


## September 14 · warmer fleet home

final result: passed

Scope: the fleet home at `/console/`, with three explicitly synthetic devices (online application, offline last observation, and an empty application). The existing website remains the visual reference. This intentionally changes the home composition, rather than copying a marketing hero pixel for pixel.

Comparison evidence in `build/console-redesign/home-workbench/`: `before-desktop.png` and `after-desktop.png`, both 1440×1000 CSS-pixel viewports, were inspected together in the same comparison input. Mobile checks cover 390×844 and 320×844 with `after-mobile.png` and `after-small-mobile.png`. Normal viewport captures avoid stitched-page artifacts.

- Typography: retains the website's Arial/Helvetica, neutral headings and muted secondary labels. The welcome title provides an entry point; board names and service names remain readable.
- Layout: a pale welcome panel and three-column application cards give the roster a useful hierarchy. Each card includes services, OS connectivity, available heap and a board link. The existing compact table is available through a labeled view toggle. Cards become two columns on smaller desktops and one on phones.
- Colors: the existing blue-gray palette and semantic connection/service dots remain. Warmth comes from hardware imagery, language and visible application context.
- Assets: reuses the website's exact `hero-transparent.png` as the decorative `workbench-board.png`, with empty alternative text and preserved image proportions. The original micros wordmark remains.
- Copy/content: distinguishes current application state, offline observations, no application and no first check-in. The home provides a short path to the CLI guide without introducing browser deployment. All service names are shown rather than hiding them behind counts.

The initial 320px inspection found a minimum-width conflict in the filter select and artwork crowding the eyebrow. Both were corrected; the document now measures 320px at a 320px viewport, and the artwork fits without covering text. Cards/Table, search/no-match/clear, offline filtering, opening a board and browser Back passed. Keyboard focus on the exact card footer button survived multiple five-second refreshes. Browser logs contained no errors or warnings. JavaScript syntax, whitespace checks and the targeted backend static-asset/CSP/session route test passed. This scoped review does not claim full assistive-technology certification.

Deployment: the four changed runtime files were deployed to the Pi after an idle-operation check and source/SQLite backup at `/home/ydzulynsky/micros/backups/home-workbench-20260914T165433Z`. Certificate-validated HTTPS verified all ten static asset hashes and existing authentication/listener boundaries. All five enrollments remained; Feather and Wroom stayed online with unchanged base and activation records and increasing uptime. The three previously offline boards remain offline. Public Cloudflare-authenticated browser rendering was not rechecked; local visual QA and origin verification are recorded separately.


## September 14 · direct Resources tab

final result: passed

User-directed navigation: **Overview · Resources · Investigate**, in that order. Resources is now a primary destination, with RAM and flash first and the existing hardware/budget/history disclosures below. Overview's unrelated free-heap and flash-capacity figures are replaced with measured RAM used/free bars, including PSRAM when enabled. CLI deployment, application controls, and board settings remain reachable from Overview and retain their contextual controls.

Evidence: `build/console-redesign/resources-tab/before-desktop.png` and `overview-desktop.png` were inspected together at 1440×1000 CSS pixels. `resources-desktop.png`, `resources-mobile.png` and `overview-mobile.png` cover the resulting views; phones were checked at 320×844. The screenshot supplied by the user establishes the original resource card. Typography, white surfaces, restrained blue/gray usage bars, borders and existing logo are preserved; the card now fits its content rather than stretching an empty panel. Labels explicitly name internal RAM, total capacity, used and free. No new visual asset is introduced.

Resources remains selected and keeps board context after reload. All three primary tabs, the memory-detail link, application controls, Overview-to-settings, and investigation options were checked through the UI. No mobile document overflow was present. Pure rendering tests cover measured internal/PSRAM data, missing/invalid telemetry, zero/full usage, legacy free-only observations and disabled PSRAM; missing telemetry never produces a fabricated usage bar. Existing browser smoke locators were updated to the new navigation. JavaScript syntax and whitespace checks passed.

Deployment verified on the Pi: all ten served static assets match local hashes, authentication and listener boundaries remain intact, all five enrollments remain, and Feather/Wroom are online with unchanged base and activation records. Backup: `/home/ydzulynsky/micros/backups/resources-tab-20260914T170751Z`. Browser console contained no errors/warnings; the local Resources tab is left open.


## September 14 · flash in the Overview summary

final result: passed

Added flash below internal RAM and enabled PSRAM in the Overview Resources card. It shows capacity and verified partition reservations, with unmapped regions hatched; it does not fabricate free flash or a measured stored-byte total. Missing or inconsistent layouts remain explicitly unavailable. Detailed flash slots and image sizes remain in the Resources tab.

Evidence in `build/console-redesign/overview-flash/`: `overview-desktop.png` (1440×1000) and `overview-mobile.png` (320×844). Typography, separators, proportions and the blue-gray palette match the preceding memory summary. The combined card and its labels fit at both sizes; no mobile document overflow or browser errors occurred. The detail link still opens the full flash view. Pure-render tests cover layout gaps, full reservation, overlapping/out-of-bounds partitions, unknown layout and missing capacity. Both flash and RAM summary tests, JavaScript syntax, and whitespace checks passed.

The before/after desktop Overview screenshots were compared together at the same viewport. The three changed runtime assets were deployed after an idle-operation check and backup at `/home/ydzulynsky/micros/backups/overview-flash-20260914T173037Z`. All ten served asset hashes verified over certificate-validated HTTPS. Five enrollments remain; Feather and Wroom are online with unchanged base/activation records. Authentication and listener isolation remain intact.


## Service flow · ApexSankey direction · September 14, 2026

Replaced the experimental boxed graph with smooth Sankey-style flows, using ApexSankey as the visual reference and a locally bundled D3 layout. Explicit publisher, channel and listener columns show reported permissions. Services with both roles appear on both sides; ribbon widths do not claim measured traffic. Missing local endpoints, partial reports, stopped services and offline observations retain distinct wording.

Visual evidence in `build/console-redesign/service-map/`: `sankey-branches-desktop.png`, `sankey-phone-start.png`, `sankey-overview-desktop.png`. Checked branching, feedback, long names, 320px containment and horizontal scrolling; click/keyboard tracing, Escape, zoom/reset and pointer panning. Permission and layout tests cover invalid/duplicate channel keys, missing masks and one-sided flows. Console API/CSP tests pass.

Deployment verified on Pi: all 13 served asset hashes match local files, CSP and no-store headers remain present, operator authentication and device-port isolation remain enforced. All five enrollments were retained; Feather and Wroom stayed online with increasing uptime, and base images/activations were unchanged. Rollback snapshot: `/home/ydzulynsky/micros/backups/service-map-20260914T180723Z`.

## Polling scroll fix — September 14, 2026

Confirmed that the five-second console refresh replaced scrollable table elements: the Channels table moved from horizontal offset 650 to 0 on the next poll. `renderObservation()` now captures page and nested table/graph/log offsets immediately before rendering an API response, restores matching regions afterward, and restores the document position after chart mounting. Intentional navigation still starts at the top. Table matching uses IDs, accessible labels or header text, with separate positions for repeated tables.

Browser verification retained the Channels offset at 650 across multiple polls while the update timestamp advanced, and retained the Overview document offset at 560. Browser errors were empty. `tests/server/scroll_refresh_test.cjs` fails against the saved old app and passes against the fix; it covers response-time scrolling, reordered/repeated tables, graph offsets, navigation and input protection. All 13 console tests and the service-flow model checks passed. JavaScript syntax and the scoped whitespace check passed.

Deployed only the changed `app.js` to tailpi using its three existing Compose files. Backup: `/home/ydzulynsky/micros/backups/scroll-refresh-20260914T191229Z`. The served file matches local SHA-256 `80ff2c6a244c309b4c190d17fde712e425efa54e2a1335581c590f63fa314979`; certificate-validated HTTPS checks retained no-store/CSP, the operator API's 401 response and the device listener's console-route 404. The browser console intentionally relies on the existing Cloudflare Access boundary. All five enrollments remain; Feather and Wroom reconnected with increasing uptime and unchanged base identities/activation records. The other three boards remain offline. The inline resource-map proposals were not part of this deployment.

## Remote endpoints and fleet map — September 14, 2026

Added globe endpoints to the existing service-flow renderer. Incoming publishers sit on the left and outgoing listeners on the right. The network bridge retains its service identity and running/stopped state. Confirmed cross-board routes are read-only console metadata, gated by the exact local application selection and checked against peer identity, binding, enrollment and online state. No route is inferred from a missing local publisher or a matching channel name. The Pi's older server has no coordination router configured, so it currently reports no cross-board routes; no routing or firmware configuration was changed.

Added a full-width Board connections section below the fleet welcome, reusing the same Sankey layout, trace, zoom and SVG renderer. Routes reported at both ends are deduplicated. All boards remain accessible, including those without routes. Selecting a board shows its services and an Open board action. Existing cards, table, filters and onboarding remain available.

Verified the graph at desktop width and 320px. At 320px, the page stays 320px wide and the 680px graph scrolls inside its 244px viewport. Keyboard tracing and Open board navigation passed. Selection, 1.25× zoom, horizontal offset 320 and page offset 147 survived repeated five-second refreshes. No browser errors were reported. Node service-map, fleet-map and scroll-refresh regressions passed; six Python flow tests and thirteen console tests passed. The built Pi image's legacy-server console integration also passed.

Deployed the combined change with all three existing Compose configurations and the read-only container preserved. The five enrollments are unchanged; feather and wroom reconnected with increasing uptime and unchanged base/application identities. Served assets match the local files. Operator token enforcement, device-only route isolation, loopback ports and runtime user remain unchanged. Backup: /home/ydzulynsky/micros/backups/remote-flow-20260914T192756Z. This backup includes the previous assets, console integration and registry snapshot.

The local 8766 preview now runs the explicitly labeled synthetic remote-flow fixture so the full layout can be evaluated without configuring real routes. Temporary verification previews were closed.

## Dedicated Connections page — September 14, 2026

Moved the fleet map out of the Boards home into #view=Connections, reached by a Connections button beside Boards in the top bar. The graph uses the full page, with no surrounding fleet cards or welcome panel; its viewport no longer has the embedded panel's vertical height cap. Existing trace, zoom, board drill-down and empty states remain available. The active workspace button is indicated, and mobile board context wraps beneath the workspace navigation.

Verified desktop rendering, 320px header and page width, reload, browser back/forward, board drill-down, return to Connections, and no browser errors. The routing/scroll, fleet-map and service-map Node regressions passed. Navigation still respects active board operations. Focus is restored after a Connections refresh, and refreshes skip active panning.

Deployed four static assets to the Pi with the existing Compose configurations. Served hashes match local files; all five enrollments and application identities are unchanged, and feather/wroom remain online with increasing uptime. Backup: /home/ydzulynsky/micros/backups/connections-page-20260914T194505Z. The user's local preview is open on Connections.
