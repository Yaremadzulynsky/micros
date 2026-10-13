# Product source

| Directory | What belongs here |
| --- | --- |
| [firmware/](firmware/README.md) | Resident OS: kernel, hardware abstraction, platform implementations and management |
| [sdk/](sdk/README.md) | Service ABI, C support and shared protobuf schemas |
| [micros_tooling/](micros_tooling/README.md) | Shared Python implementation for building, configuring and operating devices |
| [server/](server/README.md) | Management server and its browser console |
| [third_party/](third_party/nanopb/README.md) | Vendored native dependencies |

Run commands from the repository root. Start with `./micros`; `./micros setup`
installs the Python packages from this directory into the local environment.
Authored device and application declarations live in the consuming application repository.
`config/` contains reusable chip and board metadata.

Independently deployed packages live in [`services/`](../services/README.md).
Reference application services live in [`examples/services/`](../examples/services/README.md),
and test-only implementations live in `tests/fixtures/`.

The product website lives in the independent `micros-website` repository. Developer-owned
applications live outside this checkout; start one with `./micros new ../my-application`.
