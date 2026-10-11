# Micros

**Develop your microcontroller as a set of native C and C++ services.**

Micros provides service lifecycle management, declared resources, typed messages,
remote inspection and application updates without replacing the resident OS.
The goal is computer-like visibility and control on small devices. Native services
are trusted code and share memory; Micros does not provide process isolation.

[Documentation](https://docs.meetmicros.com/) ·
[Quickstart](https://docs.meetmicros.com/site/get-started/) ·
[Write a service](https://docs.meetmicros.com/site/write-a-service/) ·
[Architecture](https://docs.meetmicros.com/site/architecture/)

---

## Install and start

**Install → Create → Test → Deploy**

Start on macOS or Linux with Git, Python 3.10–3.12 and a C17 compiler.

> [!TIP]
> Your first application runs a host test on your computer. No board or server needed.

### 01 · Install the SDK and CLI

Clone the SDK into an unused tools directory and set it up once:

```sh
mkdir -p "$HOME/tools"
git clone --branch main https://github.com/Yaremadzulynsky/micros.git "$HOME/tools/micros"
cd "$HOME/tools/micros"
./micros setup

export MICROS_SDK="$HOME/tools/micros"
export PATH="$MICROS_SDK:$PATH"
command -v micros
micros --help
```

`setup` creates the SDK's Python environment and installs its dependencies.
The exports apply to this terminal; add them to your shell's startup file to keep
them for future sessions.

### 02 · Create your application

Keep application source outside the SDK checkout. From the same terminal:

```sh
cd "$HOME"
micros new my-application
cd my-application
./micros generate
./micros compose
```

This creates a hello service, generates its interfaces and resolves its deployment
declaration offline. `new` requires a directory that does not already exist.

<details>
<summary>Your application layout</summary>

```text
my-application/
  micros                         # Application CLI launcher
  micros.lock                    # Exact SDK revision
  host.toml                      # Local runtime deployment
  units/000000000000.toml         # Board deployment placeholder
  services/hello/service.toml     # Service contract and configuration
  services/hello/src/service.c    # Your service implementation
  tests/                         # Application host tests
```

</details>

The application links to your SDK checkout and checks its revision against
`micros.lock`. Keep that matching checkout available; pulling a newer SDK does
not automatically upgrade existing applications.

### 03 · Run your first test

From the application directory:

```sh
./micros test
```

The starter compiles the hello service and tests its lifecycle, greeting and
cleanup on your computer. Edit `services/hello/` in your application, then
regenerate and test as you develop. Generated output goes under `build/`.

### 04 · Choose where to run

| Run on | Start here |
| --- | --- |
| **Your computer** · macOS ARM64, Linux ARM64/x86-64 | [Deploy to the local runtime](https://docs.meetmicros.com/site/get-started/#deploy-host) |
| **ESP32** | [Set up your board](https://docs.meetmicros.com/site/set-up-an-esp32/), then [deploy your application](https://docs.meetmicros.com/site/deploy-an-application/) |
| **ESP8266 / MKR WiFi 1010** · experimental | [Choose a starter and deploy over USB](https://docs.meetmicros.com/site/experimental-usb/) |

For hardware deployment, replace the unit placeholder with your board's hardware
ID and settings before deploying.

The [full quickstart](https://docs.meetmicros.com/site/get-started/) covers setup
options, SDK selection and deployment prerequisites. Continue with
[Write a service](https://docs.meetmicros.com/site/write-a-service/), or use
[Contributing and SDK tests](https://docs.meetmicros.com/site/contributing/) to work on Micros itself.

---

## Repository map

| Folder | Purpose |
| --- | --- |
| [src/](src/README.md) | Firmware, public SDK, CLI implementation and management server/console |
| [services/](services/README.md) | Reusable, independently deployed diagnostics and tools |
| [config/](config/README.md) | Chip capabilities and board metadata |
| [examples/](examples/README.md) | Runnable examples and reference application services |
| [tests/](tests/README.md) | Automated checks, test fixtures and explicit hardware tests |
| [tools/](tools/README.md) | Build/release utilities, documentation support and agent skills |
| [docs/](https://docs.meetmicros.com/) | System model, task guides and references |

Application source and deployment declarations belong in the project created by
`micros new`, outside this SDK checkout. The product website lives in the separate
`micros-website` repository; the management server and console remain here.
`build/` is disposable generated output. `.micros/` is private operational and
recovery state: preserve it.

---

## Runtime boundaries

- Native services are trusted code without memory isolation; a fault can affect
  the whole device. The [native ABI](src/sdk/abi/include/micros/service.h) remains experimental.
- Binaries target a specific architecture, ABI and base layout. Admission checks
  compatibility, resource budgets and interfaces; it does not prove behavior.
- Application updates can pause services. The resident OS and management path
  remain in place; do not assume uninterrupted application execution.
- Recovery checks runtime health, not sensor accuracy or actuator correctness.
- Logs are bounded, volatile diagnostics, not a durable historical record.

[Architecture](https://docs.meetmicros.com/site/architecture/) · [Updates and recovery](https://docs.meetmicros.com/site/updates-and-recovery/)

---

Original Micros code is [MIT licensed](LICENSE). Bundled dependencies retain their
[upstream licenses](THIRD_PARTY_NOTICES.md).
