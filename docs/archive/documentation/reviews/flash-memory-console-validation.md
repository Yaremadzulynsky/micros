# Compact flash and RAM console views — 2026-09-08

Deployed to the existing tailpi management console using its three-file Compose
configuration. The Resources tab now has a compact flash allocation bar and
Internal heap / PSRAM usage bars. Details appear on hover, focus or touch; Escape
dismisses them and previews flip above the bar when needed. Services appears once,
with selected image slots rather than separate service-bank views.

## Data and verification

- Physical flash capacity comes from board status. Seven partition entries per
  current board come from original checksum-validated partition-table binaries,
  archived against each board's exact base ELF hash. Missing layouts stay unknown.
- Selected service packages are reconstructed against that ELF. Their complete
  graph/image digest must match the confirmed device selection before image
  lengths and physical slot offsets appear. Pending trials suppress attribution.
- Unselected slots and other storage remain unknown; no erased-byte scan or
  shared-free-space claim is made. These are build artifacts, not partition-table
  readbacks. Existing base bundles can be enriched without replacing stored bytes.
- Heap used/free and diagnostics are reported measurements. Service arena/stack
  graphics are labeled budgets, and stack peaks come from running-service
  watermarks. Private arena usage is not measured. PSRAM remains a separate pool.

Forty server tests passed, including partition checksum/overlap/bounds, immutable
bundle enrichment, missing/wrong-base handling, trial suppression, reconstructed
hash verification and physical slot ordering. Browser tests passed for flash,
RAM and existing Wi-Fi settings. Coverage includes the real CSP, escaping,
1200/736/360-pixel widths, hover/focus/Escape, zero/missing/invalid pool sizes,
disabled PSRAM and unknown service attribution.

The actual deployed console was exercised over the existing SSH tunnel to the
private operator listener for Feather, esp32-3b04 and wroom. Flash and RAM previews
rendered for all three with no JavaScript errors. All three boards remained online
with running services, increasing uptimes and unchanged base identities and
activation records. No board reflashes or service deployments were necessary.

## Reproduce

```sh
build/python/bin/python -m unittest discover -s tests/server -p '*_test.py'
# With Playwright available to Node and Chrome installed:
node tests/server/flash_browser.cjs
node tests/server/memory_browser.cjs
node tests/server/wifi_browser.cjs
```

The source/state backup on tailpi is
`~/micros/backups/flash-ui-20260908T162445Z`. It contains the original source archive
and a consistent private SQLite backup; `before-ram.tar.gz` preserves the first
flash-only deployment. Preserve the existing Compose overrides and authentication
configuration during rollback. Do not restore old state merely to revert assets.
