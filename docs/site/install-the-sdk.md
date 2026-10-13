---
title: SDK setup and troubleshooting
---

# SDK setup and troubleshooting

The [Quickstart](get-started.md#install-cli) contains the installation commands.
Use this reference for prerequisite failures, shell configuration and SDK selection.

## What setup checks {#setup-requirements}

Run setup commands from the SDK checkout.

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
[target prerequisites](set-up-an-esp32.md#target-prerequisites) for other boards.

The two `export` lines in [Quickstart](get-started.md#install-cli) apply to the current terminal. To keep them for new
terminals, add those same lines to your shell's startup file (for example
`~/.zshrc` for zsh or `~/.bashrc` for interactive bash), then open a new terminal.
Keep this tools checkout separate from your application code.

## Application launcher and SDK pin

`micros new` creates an ignored `.sdk` link to your checkout. Inside an application,
`micros` and `./micros` select that project and validate `micros.lock`. The local
launcher works without the SDK on PATH. Use `micros sdk COMMAND` to bypass project
defaults deliberately; `MICROS_SDK` selects an explicit checkout.

`micros.lock` records the exact SDK Git commit. Pulling a newer SDK does not update
existing projects' locks. Keep the matching checkout available and upgrade projects
deliberately. The lock does not capture uncommitted SDK changes.

## Installed Python CLI

The wheel/pipx entrypoint uses the same dispatcher. Select a checkout with
`MICROS_SDK` when creating a project through an installed CLI. Existing projects
use `.sdk` or their exact lock revision; the resolver can cache a missing pinned
SDK. `MICROS_OFFLINE=1` prevents downloads. No package or release wheel has yet
been published; use the public Git checkout from Quickstart.
