# Working in micros

Run project commands from the repository root. Start with the
[repository map](docs/site/contributing.md#repository-map), the relevant folder's README and any
nested `AGENTS.md`. Use [contributor checks](docs/site/contributing.md) to validate changes.

- Preserve unrelated changes, application-owned recipes and private `.micros/`
  state. Keep credentials, private base artifacts and operational history out of commits.
- Put generated output and investigation evidence in ignored `build/` directories.
  Retain errors, gaps and device/base/activation identity when collecting evidence.
- Keep application code in consuming projects. Follow the folder ownership map;
  diagnostic packages live in `services/diagnostics/`, reusable host code in
  `src/micros_tooling/`, and operational workflows in `tools/skills/`.
- Report relevant checks and distinguish host/build verification from hardware results.
  Give each maintained explanation one home; link to contracts and working examples.

## Board investigations

For requests to inspect, diagnose or test a board, read and follow both
[micros-device-access](tools/skills/micros-device-access/SKILL.md) and
[micros-diagnose-system](tools/skills/micros-diagnose-system/SKILL.md), even if the
agent loader has not discovered them. Reuse collected evidence and carry authorized
functional tests through their prerequisites, results and cleanup. Select further
workflows from the [skill catalog](tools/skills/README.md).
