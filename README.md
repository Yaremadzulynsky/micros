# Micros

**Develop your microcontroller as a set of native C and C++ services.**

Micros provides service lifecycle management, declared resources, typed messages,
remote inspection and application updates without replacing the resident OS.
The goal is computer-like visibility and control on small devices. It is not Linux
and does not provide process memory isolation.

## Install and start

Follow the [Quickstart: install the SDK and CLI](https://docs.meetmicros.com/site/get-started/#install-cli).
It covers cloning current `main` into a tools directory, running setup once,
adding the launcher to PATH, and creating a separate application. The repository
is public. No board or server is needed
for the first generation, composition and host test.

The checkout route uses `micros new` to create a project and its generated
`./micros` launcher for application commands. Each `service.toml` owns a service's
implementation and contract; `units/<hardware-id>.toml` owns board-specific choices.
`micros.lock` checks the SDK revision. Keep application source outside this repository.

[Documentation](https://docs.meetmicros.com/) ·
[Write a service](docs/site/write-a-service.md) ·
[Contributing and SDK tests](CONTRIBUTING.md)

The older `v0.1.0-preview.1` release has [historical instructions](docs/site/developer-preview.md)
and [dated validation evidence](docs/site/preview-evidence.md). It is not the
current installation route. Other MCU targets, cross-board coordination and base
OTA remain experimental; check the relevant target guide before using hardware.

## Repository map

| Folder | Purpose |
| --- | --- |
| [src/](src/README.md) | Firmware, public SDK, CLI implementation and management server/console |
| [services/](services/README.md) | Reusable, independently deployed diagnostics and tools |
| [config/](config/README.md) | Chip capabilities and board metadata |
| [examples/](examples/README.md) | Runnable examples and reference application services |
| [tests/](tests/README.md) | Automated checks, test fixtures and explicit hardware tests |
| [tools/](tools/README.md) | Build/release utilities, documentation support and agent skills |
| [docs/](docs/index.md) | System model, task guides and references |

Application source and deployment declarations belong in the project created by
`micros new`, outside this SDK checkout. The product website lives in the separate
`micros-website` repository; the management server and console remain here.
`build/` is disposable generated output. `.micros/` is private operational and
recovery state: preserve it. Archived documentation retains its original paths
and measurements; it does not describe the current implementation.

## Understand the limits

- Native services are trusted code without memory isolation; a fault can affect
  the whole device. The [native ABI](src/sdk/abi/include/micros/service.h) remains experimental.
- Binaries target a specific architecture, ABI and base layout. Admission checks
  compatibility, resource budgets and interfaces; it does not prove behavior.
- Application updates can pause services. The resident OS and management path
  remain in place; do not assume uninterrupted application execution.
- Recovery checks runtime health, not sensor accuracy or actuator correctness.
- Logs are bounded, volatile diagnostics, not a durable historical record.

[Architecture](docs/site/architecture.md) · [Updates and recovery](docs/site/updates-and-recovery.md)

Original Micros code is [MIT licensed](LICENSE). Bundled dependencies retain their
[upstream licenses](THIRD_PARTY_NOTICES.md).
