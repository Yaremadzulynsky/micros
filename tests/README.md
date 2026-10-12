# Cross-component validation

CTest registers host lifecycle/loader, IPC/codec, package/admission, activation,
configuration/generation, Wi-Fi, terminal deployment and management relay/console
checks. Use `ctest --test-dir build/host -N` for the configured inventory and
`ctest --test-dir build/host --output-on-failure` to run it after building.

For console onboarding browser checks, with Playwright available in `NODE_PATH`
and Chrome installed, run `node tests/server/console_onboarding_browser.cjs`.
It starts isolated synthetic fixtures, checks sign-in recovery and the empty-server
enrollment/deployment journey at desktop and 320px widths, then stops them.
Screenshots go under `build/console-onboarding/` (or `MICROS_BROWSER_OUTPUT`).
No operator credentials or physical boards are used. For manual preview,
`build/python/bin/python tests/server/console_design_fixture.py --empty` opens
the same first-use state.

- `runtime/`, `loader/`, `integration/`: native loading, lifecycle and fault fixtures.
- `ipc/`, `interfaces/`, `configuration/`, `services/`: bounded communication, generated APIs, settings and button/color behavior.
- `deployment/`, `server/`: storage, activation, admission, CLI, Wi-Fi and server behavior.
- `base_ota/`: base-only update state machine, trial rollback, client and layout checks.
- `hardware/`: explicit device tests that can reset the board and replace service graphs.
- `fixtures/`: independently built test services, separate from application examples.
- `docs/`: repository entry-point links, checked with the documentation build's validator.

Compile-only public ABI checks live in `tools/checks/`. See
[contributor setup](../CONTRIBUTING.md) for the current host prerequisites.
CTest's `console_offline` runs the existing graph, memory, flash and refresh
checks with Node.js and no browser. It reports a skip when Node is missing; CI
installs Node so these checks are required there. Browser scripts remain explicit
operations: inspect each fixture's prerequisites before running it, because some
use live boards or private state.

Host configuration headers are generated from `tests/fixtures/configuration/`, independently of root application enablement. `button_restart` tests the real IPC ring and production consumers across independent reloads; `button_color_cycle` covers edge, loss and debounce semantics.

`diagnostics/` exercises the deployable channel probe, signal recorder and replay
source with production generated codecs and simulated clocks/GPIO/transport. It
also checks replay schema/bounds validation, evidence preservation, uncertain
writes, and authenticated shared-stream access. CTest registers these as
`diagnostic_services` and `diagnostic_clients`. Physical measurements require
separate hardware validation.
