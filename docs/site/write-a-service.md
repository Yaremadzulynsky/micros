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

## 01 · Change the heartbeat {#change-the-heartbeat}

The project from [Quickstart](get-started.md) contains a working heartbeat in
`services/hello/`. Its C code opens the declared `greeting` timer and writes
`Hello world` to the log. It needs no GPIO or wiring and runs on the host or a board.

The service's `config_schema` defines `interval_ms`, its default and bounds.
Your `host.toml` or selected `units/<hardware-id>.toml` chooses the value:

```toml
[services.hello]
source = "services/hello" # Use "../services/hello" in a unit file.
contract = "service.toml"
memory = { arena = "RAM", stack_bytes = 4096 }
config = { interval_ms = 250 }
```

Edit the existing table rather than adding a duplicate. Run `./micros compose`
to validate a board unit, or `./micros host build` to compile `host.toml`.
`./micros test -v` runs the real heartbeat with a deterministic timer stub: it
checks the default and selected interval, output, and cleanup without waiting or
using hardware. `./micros host deploy` and `./micros host logs` let you observe it.
Stop the local application with `./micros host stop` when finished.

Generated hooks decode settings and close the timer after `hello_on_stop`.
You do not write a service descriptor or duplicate resource cleanup. Hooks must
return in bounded time; see [Service API](service-api.md).

Once a version has been installed, change `version` in the service's `service.toml`
before deploying different code or settings—for example `1.1.0` to `1.1.1`.
Installed versions identify immutable packages, which preserves recovery history.

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

Creating source does not deploy it. Add this table to your unit file, alongside
its existing identity, board and services:

```toml
[services.counter]
source = "../services/counter"
contract = "service.toml"
memory = { arena = "RAM", stack_bytes = 4096 }
expose_commands = ["read", "increment", "reset"]
```

Run `./micros compose` to validate. To build it locally, add the same selection to
`host.toml` with `source = "services/counter"`, then run `./micros host build`.
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

The next concept to learn is a publisher and subscriber on **one board**: a sensor
publishes readings, and another service reacts to them through declared channels.
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
