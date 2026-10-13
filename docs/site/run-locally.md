---
title: Run locally
---

# Run locally

Run the simulated climate application on your computer. No board, server or
wiring is required. This is an optional alternative to device enrollment.

## 1 · Run the application {#deploy-host}

[Install micros](get-started.md#install-cli) and
[create an application](get-started.md#create-your-project), then run these commands
from its directory. Skip device enrollment. Local deployment supports Linux
ARM64/x86-64 and macOS ARM64.

```sh
./micros host deploy
./micros host status
./micros host logs
```

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

## 2 · Change the fan policy {#first-change}

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

## Run checks

```sh
./micros test
```

This compiles the real services and protobuf codecs with a deterministic clock
and test bus. It checks the temperature cycle, hysteresis, message freshness and
cleanup; it does not start a persistent application or test physical hardware.
Use `./micros test -v` for individual results or `-k NAME` to filter tests.
The generated README explains the service flow; see
[contributor checks](contributing.md) for the full SDK host suite.

Use `./micros compose -d host` to validate the host configuration offline.
With no board enrolled, `./micros compose` selects the host. With one board, it
selects that board; multiple boards require an explicit `-d HARDWARE_ID`.

## Local runtime details

`units/host.toml` selects local services using the same contracts and configuration as
a board application, without a hardware ID or board definition. The first deploy
builds the SDK's native runtime and your services. `host build` only produces
packages under `build/host-packages`. Installed packages and activation records
live in `.micros/host`; keep that directory to retain recovery state. Existing
projects need the matching service sources and `protos/` as well as the unit;
copying only `host.toml` does not create those dependencies.

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
