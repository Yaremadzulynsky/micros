# Commands and development utilities

Start with the root `./micros` command. The installed launcher and checkout launcher
share the implementation in [`src/micros_tooling/`](../src/micros_tooling/README.md).

- `cli/`: lower-level script interfaces for remote and desktop runtime control.
- `packaging/`: demonstration/fixture package builders and a compatibility command.
- `checks/`: native ABI compile checks.
- `release/`: reproducible builds and release validation.
- `docs/`: documentation build support.
- `skills/`: agent workflows for device access and diagnosis.
- `vendor/`: reproducible third-party frontend bundle inputs.

Firmware builders and platform clients live in `src/micros_tooling/platforms/`.
Python dependencies are pinned in `requirements-dev.txt`; `./micros setup`
installs them into `build/python`. See [contributor checks](../docs/site/contributing.md).
