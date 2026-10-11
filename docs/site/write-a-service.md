---
title: Write a service
hide:
  - toc
---

<span class="docs-editorial"></span>

Build · Write a service
{: .arch-eyebrow}

# Write a service

Create a hook-based counter in the project from [Quickstart](get-started.md).
The generator owns lifecycle plumbing; your C file owns behavior.
{: .arch-intro}

## 01 · Declare the counter {#declare-the-counter}

Create `services/counter/service.toml`:

```toml
[service]
name = "example.counter"
version = "0.1.0"

[service.build]
api = "counter"
lifecycle = "hooks"
sources = ["src/service.c"]
descriptor = "micros_descriptor"

[service.config]

[service.types.Count]
type = "uint32"

[service.commands.increment]
returns = { count = "Count" }
```

From the application directory:

```sh
./micros scaffold-service services/counter
./micros generate --service services/counter
```

Scaffolding creates `src/service.c` and `src/counter_state.h` once; it refuses to
overwrite them. Generation updates derived files under `build/services/counter/generated/`.

## 02 · Implement behavior {#implement-behavior}

In `counter_state.h`, replace the placeholder `reserved` field with:

```c
uint32_t count;
```

In `service.c`, replace the generated `counter_handle_increment` body:

```c
micros_result_t counter_handle_increment(counter_context_t *ctx,
                                        uint32_t *out_count)
{
    *out_count = ++ctx->state.count;
    return MICROS_OK;
}
```

Leave the generated start/step/stop stubs returning `MICROS_OK`. State begins
zeroed for each lifetime; this unsigned counter wraps after `UINT32_MAX` and
resets on restart. It is a demonstration, not persistent storage.

Hooks execute serially on the service worker and must return in bounded time.
Generated lifecycle code opens declared resources before start and releases them
after stop, including partial startup cleanup. Do not close generated-owned handles
inside your hooks. See [Service API](service-api.md) for the native contract.

## 03 · Select it on your board {#select-it-on-your-board}

Add to your unit file, alongside its existing identity and board:

```toml
[services.counter]
source = "../services/counter"
contract = "service.toml"
memory = { arena = "RAM", stack_bytes = 4096 }
expose_commands = ["increment"]
```

Run `./micros compose` to validate. Exposing commands adds transport resources;
see [Service commands](service-commands.md) before deploying. On a supported
ESP32 base, [deploy](deploy-an-application.md), open `./micros shell -d NAME`, and run:

```text
call example.counter increment
```

The first completed call returns count 1; the next returns 2. Without command
exposure the service can load, but the remote call is unavailable.

## 04 · Change the contract {#change-the-contract}

After committing an application baseline, compare later edits with:

```sh
./micros contract-diff services/counter --base HEAD
./micros scaffold-service services/counter --preview --base HEAD
./micros generate --service services/counter
```

The preview prints changed hook signatures without replacing your implementation.
Bounds or enum changes can alter behavior without a C signature change; the diff
makes them visible. Add behavior tests in your project's `tests/` directory;
`./micros test` runs `*_test.py` files.

The starter hello uses the supported manual ABI lifecycle. Its
[complete source](../../examples/hello-service/src/service.c) remains the example
for that style; new hook services need not duplicate its resource plumbing.
