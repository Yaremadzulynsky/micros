# Repository reorganization — September 14, 2026

The CLI and server now share the `micros_tooling` Python package. Application
services and resident management have separate homes, current website code has
a permanent location, and early executable experiments are explicitly archived.

| Previous location | Current location |
| --- | --- |
| `tools/management/*.py` | Responsibility-based packages under `micros_tooling/` |
| `tools/platforms/` | `micros_tooling/platforms/` |
| `tools/packaging/build_esp32_service.py` | `micros_tooling/platforms/esp32/build_service.py` |
| `tools/packaging/package.py` | `micros_tooling/storage/native_image.py` |
| `services/management/` | `firmware/management/` |
| `prototypes/product-showcase/` | `website/` |
| `prototypes/service-coordination/` | `archive/service-coordination/` |
| ESP32 M1 project, serial client and hardware test | `archive/esp32-m1/` |

The primary `./micros` interface and existing operational unit recipes remain
supported. Internal Python imports and direct script paths changed; repository
callers, tests, CMake rules, Docker inputs, editor configuration and documentation
use the new locations. New composed deployments are the preferred authoring path;
this does not rewrite or deploy the existing operational units.

The previous root architecture account is preserved in
[the archive](../../v1-architecture.md). Current ownership is described in
[the repository guide](../../../../README.md#repository-map).

## Validation

- Host CMake configure and build passed.
- 54 of 56 CTest entries passed on the first parallel run. Existing composition
  command code shadowed the deployment receipt formatter; giving its formatter
  a distinct local name fixed the terminal-deployment regression, which passed
  on rerun. The runtime lifecycle test timed out under parallel load and passed
  in isolation (10.5 seconds within its 20-second limit); runtime code was unchanged.
- ESP32 current runtime built successfully using the configured Feather board,
  including the relocated resident management sources. No hardware was flashed.
- All three deployment declarations and the standalone root recipe resolved.
- Server imports passed in a temporary directory containing only the Docker COPY
  inputs. An actual Docker image build was not performed.
- Website production build and four hosting-bundle tests passed with Node 24.
  The default shell Node runtime could not run Vite's crypto API; the installed
  Node 24 runtime was used explicitly.
- Flash summary, memory summary and service-flow JavaScript tests passed.
- Archived coordination prototype passed all 23 contract tests.
- MkDocs build, Python compilation, repository import-path checks and diff
  whitespace validation passed.

Existing changes were preserved during the moves. No commit or deployment was made.
