# Working in this micros application

Read this project's [README.md](README.md) and the pinned framework's
[AGENTS.md](.sdk/AGENTS.md) before making changes. Resolve links in the framework
instructions relative to `.sdk/`. Its repository layout and contributor commands
apply to the SDK; run application commands from this project's root.

If `.sdk` is unavailable, locate the matching SDK selected by `micros.lock` or
`MICROS_SDK` and read its `AGENTS.md`. Do not substitute instructions from a newer
framework revision. Keep this file in the application so project-specific
instructions can be added here.

- Application service code belongs in `services/`. The framework, CLI, firmware
  and management console belong to the SDK dependency; do not edit that dependency
  as a side effect of application work.
- `units/host.toml` selects the local host application. Successful enrollment creates
  `units/<hardware-id>.toml`, the complete configuration for one physical board.
  Do not invent a placeholder board identity. Boards deploy independently.
  Enrollment installs the SDK's pristine simulated climate example by default;
  application-owned edits require a subsequent explicit deployment.
- Use native service declarations: `config_schema` defines types, defaults and
  bounds; application `config` selects values. Keep generated output in `build/`.
- Use `./micros compose -d host`, `./micros generate` and `./micros test` before
  enrollment. Validate a board with `./micros compose -d HARDWARE_ID`. Multiple
  boards require an explicit target. Compilation and host tests are not hardware verification.
- Preserve authored units, service code, `micros.lock`, private `.micros/` state
  and recovery history. Operator credentials belong in user-level configuration,
  never tracked source. `.sdk` is an ignored local dependency link.

For board investigations, follow the pinned SDK's
[device-access](.sdk/tools/skills/micros-device-access/SKILL.md) and
[system-diagnosis](.sdk/tools/skills/micros-diagnose-system/SKILL.md) workflows.
Select the board explicitly and verify its live identity and release rather than
assuming the authored configuration is deployed. Further workflows are in the
[skill catalog](.sdk/tools/skills/README.md).
