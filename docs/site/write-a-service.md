---
title: Write a service
hide:
  - toc
---

<span class="docs-editorial"></span>

Build · Write a service
{: .arch-eyebrow}

# Write a service

Start with behavior you can observe, then add state and commands. Micros owns
lifecycle plumbing; your service owns its behavior and declares what it needs.
{: .arch-intro}

## 01 · Change the simulated climate application {#change-the-heartbeat}

The project from [Quickstart](get-started.md) has three services and two typed
channels. `climate-sensor` calls a separate simulated sensor driver on a timer;
`fan-controller` applies hysteresis; `status-display` logs readings and fan state.
All input and output are simulated, with no GPIO or wiring.

To change sampling, edit the existing `config.interval_ms` value under
`[services.climate_sensor]` in your selected unit. The service's `config_schema`
defines its default and bounds. Keep the display's `stale_after_ms` above the
sample interval. To change policy, edit `on_millicelsius` and `off_millicelsius`
under `[services.fan_controller]`, keeping off below on.

Run `./micros compose -d host` and `./micros test -v`. The tests compile the actual
services, generated lifecycle and protobuf codecs with a deterministic test bus.
`./micros host deploy` and `./micros host logs` show the complete application;
finish with `./micros host stop`. For an enrolled board, use `./micros deploy -d ID`.

Generated hooks decode settings, dispatch typed subscriptions and close resources.
Service hooks must return in bounded time; see [Service API](service-api.md).
The [service reference](service-configuration.md) describes the declarations.

Host packages are immutable by name/version. Bump the changed service version
before redeploying changed code or settings, for example `1.0.0` to `1.0.1`.
Board releases use content hashes. See the [unit reference](unit-configuration.md).

## 02 · Add state and commands {#declare-the-counter}

Create a complete working counter in one command:

```sh
./micros scaffold-service services/counter --example counter
./micros generate --service services/counter
```

This creates `service.toml`, `src/service.c` and `src/counter_state.h`; it refuses
to overwrite an existing directory. The service is named `app.counter`. Its
`Count` type is shared by the declared commands and generated C signatures.

The example starts at zero, returns its value through `read`, increments through
`increment`, and clears it through `reset`. Its state belongs to one service
instance, resets on restart, and wraps after `UINT32_MAX`. It is not persistent
storage. The handler for increment is only:

```c
micros_result_t counter_handle_increment(counter_context_t *ctx,
                                         counter_count_t *out_count)
{
    *out_count = ++ctx->state.count;
    return MICROS_OK;
}
```

## 03 · Select it in an application {#select-it-on-your-board}

Creating source does not deploy it. To try the counter on an ESP32, keep the
unit's identity and board tables, and replace its three climate service tables
and two climate channels with the selection below. Keep the climate source files
so you can restore the original unit later. The counter plus its generated command
bridge uses two service slots; adding both to the three-service starter would
exceed the four-slot limit.

```toml
[services.counter]
source = "../services/counter"
contract = "service.toml"
memory = { arena = "RAM", stack_bytes = 4096 }
expose_commands = ["read", "increment", "reset"]
```

Run `./micros compose -d HARDWARE_ID` to validate that board. To build the counter
locally instead, replace the climate services and channels in `units/host.toml`
with the counter table, **omitting `expose_commands`**, then run
`./micros compose -d host` and `./micros host build`. The remote command bridge
requires a supporting ESP32 base; it is not a host command transport.
Host build/deployment checks do not prove physical board behavior.

Command exposure adds a transport bridge and consumes service/channel resources;
see [Service commands](service-commands.md). On a supported ESP32 base,
[deploy](deploy-an-application.md), open `./micros shell -d NAME`, and run:

```text
call app.counter read
call app.counter increment
call app.counter reset
```

The returned counts are 0, 1 and 0. Without explicit command exposure the service
can load, but those remote calls are unavailable.

## 04 · Build your own behavior {#implement-behavior}

For an empty hook service, use:

```sh
./micros scaffold-service services/my-service --new
```

For a declaration you already wrote, omit `--new`; scaffolding derives the hooks
from that declaration and preserves existing implementation files. Generated
interfaces live under `build/services/`, separate from application source.

The starter already connects publishers and subscribers on **one board**.
Extend its messages or add a new subscriber to explore independent readers.
Follow [Connect service ports](connect-service-ports.md) and choose real pin bindings only once your hardware
is known. A blinking LED is an optional hardware exercise, since boards have
different LED pins and some expose none; it is not a prerequisite for learning
services, settings or commands.

## 05 · Change the contract {#change-the-contract}

After committing an application baseline, compare later edits with:

```sh
./micros contract-diff services/counter --base HEAD
./micros scaffold-service services/counter --preview --base HEAD
./micros generate --service services/counter
./micros test -v -k counter
```

The preview shows changed hook signatures without replacing your implementation.
Bounds or enum changes can alter behavior without a C signature change; the diff
makes them visible. Add behavior tests under `tests/` using `*_test.py` filenames;
`-k counter` filters your tests and does not generate tests for a new service.

For advanced manual lifecycle work, the [manual hello source](../../examples/hello-service/src/service.c)
shows the ABI directly. The starter uses hooks so that plumbing does not obscure
the behavior you are trying to write.
