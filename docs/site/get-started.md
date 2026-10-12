---
title: Quickstart
hide:
  - toc
---

<span class="docs-editorial"></span>

Start · Quickstart
{: .arch-eyebrow}

# Quickstart

Clone the SDK once, set up its Python tools, and create your application in a
separate directory. These instructions use current `main`.
Your first application has three services: simulated climate readings, fan control
and a log display, connected by two typed channels. No board, server or external
sensor is needed to generate, test or run it locally.
{: .arch-intro}

## 01 · Install the SDK and CLI {#install-cli}

Use macOS or Linux with Git to clone the SDK. The public SDK can be cloned without GitHub authentication.
Choose an unused installation directory; this example uses `~/tools/micros`:

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

`command -v micros` should show your checkout's `micros` file.

### What setup checks {#setup-requirements}

`./micros setup` reports each prerequisite, installs missing tools, then checks
again. It prepares Git, Python 3.10–3.12 with virtual-environment support, C17 and
C++17 compilers, Make, CMake 3.24+, Ninja and the SDK's Python dependencies.
Python packages and missing CMake/Ninja installations live in `build/python`;
the CLI makes these build tools available automatically.

To inspect your computer without installing or downloading anything:

```sh
./micros setup --check
```

The check exits successfully only when all host prerequisites are ready.
Automatic system-package installation uses **Homebrew on macOS**, or **apt/dnf
on Linux**; Linux may ask for your sudo password. If macOS needs Apple's Command
Line Tools, setup opens their installer: finish it and rerun setup. If Homebrew
is missing, install it from [brew.sh](https://brew.sh/) first. Other Linux package
managers require you to install the reported system tools yourself.

Setup uses an existing supported Python when available. `MICROS_PYTHON` can select
one explicitly; an invalid override or an incompatible existing `build/python`
is reported and preserved. Linux repositories must provide a supported Python.
Setup does not upgrade the OS or change your shell startup files.

Board toolchains, Docker and contributor-only tools such as Node.js are separate.
Enrollment installs missing ESP32 and ESP8266 build tools automatically. Use
`./micros setup --esp32` to install the pinned ESP32 SDK ahead of time; see the
target guide for other boards.

The two `export` lines apply to the current terminal. To keep them for new
terminals, add those same lines to your shell's startup file (for example
`~/.zshrc` for zsh or `~/.bashrc` for interactive bash), then open a new terminal.
Keep this tools checkout separate from your application code.

## 02 · Create your project {#create-your-project}

From a directory where you want to keep applications, use a new project name:

```sh
cd "$HOME"
micros new my-application
cd my-application
./micros compose -d host
./micros generate
```

Enrollment detects the board and selects its profile and example memory budget.
The optional `new --platform` flag remains accepted for compatibility, but creates
no board unit. See [USB deployment](experimental-usb.md) for experimental targets.

All launchers use the same CLI. `micros new` creates an ignored `.sdk` link to
this checkout. Inside the application (including subdirectories), both `micros`
and `./micros` select its project and validate `micros.lock`. The local launcher
also works when the SDK is not on PATH. Use `micros sdk COMMAND` to bypass project
defaults deliberately. Set `MICROS_SDK` to override the link with a matching checkout.

Generation should report all three services' interfaces without contacting a board. New
projects contain `units/host.toml`; enrollment adds a unit for the actual board. `new` refuses
to overwrite an existing directory. `micros init` provisions a board, not a project.

```text
my-application/
  AGENTS.md
  micros
  micros.lock
  units/host.toml
  services/climate-sensor/       # Calls the simulated sensor driver
  services/fan-controller/       # Applies temperature hysteresis
  services/status-display/       # Logs readings and simulated fan state
  protos/climate/                # Reading protobuf and interface
  protos/fan/                    # Fan status protobuf and interface
  tests/
```

The generated `AGENTS.md` contains application-specific guidance and links to the
pinned SDK's `.sdk/AGENTS.md` and device workflows. It is a regular project file
you can extend, so framework guidance stays tied to your chosen SDK revision.

`micros.lock` records the checkout's exact Git commit. The application launcher
rejects a different revision; pulling a newer SDK does not silently update an
existing project's lock. Keep the matching checkout available and upgrade
projects deliberately. The lock does not capture uncommitted SDK changes.

Edit your application's `services/`, not the SDK example. Generated files
belong under `build/`.

<span id="run-hello"></span>

## 03 · Run the simulated climate application {#run-climate}

With a C17 compiler installed, run from your application directory:

```sh
./micros test
```

The starter has three hook-based services: a climate sensor calls a deterministic
simulated driver, a fan controller applies a temperature policy, and a status
display logs both typed channels. No external input or hardware is required.
The test compiles the real services and protobuf codecs with a deterministic
clock and test bus, checking the repeating cycle, hysteresis, freshness and cleanup.
`./micros test -v` shows individual results; `-k NAME` filters them. This is not a
physical board test. The generated README explains the flow and first changes.
See [contributor checks](contributing.md) for the full SDK host suite.

### Deploy a persistent local application {#deploy-host}

After setup on Linux ARM64/x86-64 or macOS ARM64, run from the generated
application directory:

```sh
./micros host deploy
./micros host status
./micros host logs
```

`units/host.toml` selects local services using the same contracts and configuration as
a board application, without a hardware ID or board definition. The first deploy
builds the SDK's native runtime and your services. `host build` only produces
packages under `build/host-packages`. Installed packages and activation records
live in `.micros/host`; keep that directory to retain recovery state. Existing
projects need the matching service sources and `protos/` as well as the unit;
copying only `host.toml` does not create those dependencies.

After several sample periods, logs contain lines like:

```text
Simulated climate #5: temp=28000 mC humidity=490 permille fan=ON
Simulated climate #9: temp=24000 mC humidity=470 permille fan=OFF
```

`28000 mC` means 28°C; `490 permille` means 49% relative humidity. Sample IDs
advance; their exact value depends on when you read the log. The driver repeats
20, 22, 24, 26, 28, 30, 28, 26, 24, 22°C. The fan starts off, turns on at or above
28°C and stays on until at or below 24°C. The display logs decisions; it does not
drive a physical fan. Local host applications do not appear in the board console.

### Make one change and verify it {#first-change}

In `units/host.toml`, change the existing fan controller setting to:

```toml
config = { on_millicelsius = 26000, off_millicelsius = 24000 }
```

Host packages are immutable by service name/version. Change `version = "1.0.0"`
to `version = "1.0.1"` in `services/fan-controller/service.toml`, then run:

```sh
./micros compose -d host
./micros test
./micros host deploy
./micros host logs
```

In the new run, sample 4 at 26°C should report `fan=ON`; with the original
threshold it reported `fan=OFF`. At 24°C it should still switch off. The tests
exercise service behavior with controlled fixtures; inspect the deployed logs to
verify your selected unit settings. Finish the local run with:

```sh
./micros host stop
```

`./micros host boot` starts its confirmed selection again later.

Use `./micros compose -d host` to validate the host configuration offline.
With no board enrolled, `./micros compose` selects the host. With one board, it
selects that board; multiple boards require an explicit `-d HARDWARE_ID`.

The controller continues after the command exits. `stop` shuts down this local
graph; `boot` reconstructs its confirmed selection. This does not install an OS
startup service. Change a service's version when changing its code or settings:
installed name/version pairs are immutable.

Deployment replaces the whole graph with a brief stop. The receipt separates
`requested`, `active`, `last_good`, and `last_failure`. A failed trial can restore
the last-good graph while retaining the requested selection; deployment then
returns an error. The five-second trial checks runtime progress, not application
correctness. Native services share one address space; this path supports up to
four services and no physical GPIO. A stuck native worker requires whole-process
recovery. Sandboxes that deny Unix sockets cannot run the managed controller;
that is an environment limitation, not a successful deployment.

### Optional: installed Python CLI

The wheel/pipx entrypoint uses the same dispatcher and command options. Select a
checkout with `MICROS_SDK` when creating a project through a standalone installed
CLI. Existing projects use their `.sdk` link or exact `micros.lock` revision;
when no matching checkout is available, the resolver can cache that pinned SDK.
Use `MICROS_OFFLINE=1` to prevent downloads. There is no separate hardcoded default
SDK revision. No package or release wheel has yet been published.

## 04 · Use a board {#use-a-board}

[Set up a board](set-up-an-esp32.md). After successful enrollment,
`units/<hardware-id>.toml` contains the detected identity, board profile, flash
capacity and the simulated climate application. Each additional enrolled board gets its own unit;
existing units and service code are preserved. Enrollment installs the SDK's
simulated climate starter and confirms all three services through the server.
Use `--no-starter` for a management-only board. Run `./micros compose -d HARDWARE_ID`
to validate your unit offline, then `./micros deploy -d HARDWARE_ID` for later edits.
Review the profile and wiring before adding hardware services: enrollment cannot
identify attached peripherals. For example, a Feather V2 uses
`adafruit_feather_esp32_v2` and `flash_mb = 8`.

Multiple units require `-d HARDWARE_ID`. Hardware IDs work for offline composition;
friendly device names require the configured server roster.

| Target | Starting point |
| --- | --- |
| macOS ARM64; Linux ARM64/x86-64 | [Local deployment](#deploy-host) and host tests |
| Original ESP32, 4/8 MiB flash | [Board setup](set-up-an-esp32.md) |
| ESP8266, 4 MiB; Arduino MKR WiFi 1010 | [Experimental USB deployment](experimental-usb.md), including target-specific unit settings and prerequisites |

Continue with [Write a service](write-a-service.md) or
[Deploy and update](deploy-an-application.md).
