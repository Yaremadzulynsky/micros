---
title: Quickstart
hide:
  - toc
---

# Quickstart

Install micros, create an application, and enroll a USB-connected board.
The starter runs simulated climate, fan-control and display services—no sensors
or other wiring required.

**No board?** [Run the starter locally](run-locally.md) or
[try an interactive tutorial in your browser](../tutorials/index.md).

## 1 · Install {#install-cli}

On macOS or Linux with Git, use a new directory:

```sh
mkdir -p "$HOME/tools"
git clone --branch main https://github.com/Yaremadzulynsky/micros.git "$HOME/tools/micros"
cd "$HOME/tools/micros"
./micros setup
export MICROS_SDK="$HOME/tools/micros"
export PATH="$MICROS_SDK:$PATH"
```

Keep this terminal open. [Setup help](install-the-sdk.md) covers missing tools
and keeping `micros` on PATH.

## 2 · Create an application {#create-your-project}

```sh
cd "$HOME"
micros new my-application
cd my-application
```

## 3 · Enroll your device {#use-a-board}

Connect an original ESP32, ESP8266 (4 MiB), or MKR WiFi 1010 by USB.
Use 2.4 GHz Wi-Fi; check [target prerequisites](set-up-an-esp32.md#target-prerequisites).
For a new local server, Docker with Compose must be installed and running.

**Enrollment replaces the board's firmware.**

```sh
./micros enroll
```

Choose an existing server or **Create a new server on this computer** and accept
its startup prompt. Then select the board and enter its name and Wi-Fi details.
Enrollment sets up the server and console when requested, installs the runtime,
creates `units/HARDWARE_ID.toml`, and deploys the starter. The first build can take
several minutes. [Enrollment help](set-up-an-esp32.md) covers recovery and certificates.

## 4 · Check the result {#open-the-console}

```sh
./micros server console
```

Expect your board online with three running services. Replace `HARDWARE_ID` below
with the ID printed by enrollment to read simulated climate and fan-state logs:

```sh
./micros logs -d HARDWARE_ID --follow
```

Ctrl-C stops following logs. [Console connection help](run-management-server.md#open-the-console).

**Next:** [Learn the micros way](../tutorials/index.md), then
[deploy your changes](deploy-an-application.md).
