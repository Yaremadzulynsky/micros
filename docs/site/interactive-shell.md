---
title: Interactive shell
hide:
  - toc
---

<span class="docs-editorial"></span>

Use · Interactive shell
{: .arch-eyebrow}

# Interactive shell

From your application directory:

```sh
./micros shell
```

Choose a board from the picker, or use `./micros shell -d NAME`. The shell runs
on your computer using its operator configuration; it does not install an OS
shell on the MCU. A saved direct HTTPS profile supports basic inspection too.

## 01 · Inspect and follow {#inspect-and-follow}

```text
status
services
services 0
watch --interval 2 services
logs --follow
commands
ports
help
exit
```

`status --details` and `services --details` show additional counters; `--json`
retains machine-readable data. `ls` aliases `services`. Tab completes discovered
names/fields; refresh `commands` or `ports` after deployment.

Ctrl-C stops the current watch/follower and returns to the prompt. Ctrl-D or
`exit` quits. Read-only polling can resume after outages; authentication and
certificate errors stop it. `reconnect` reloads credentials for the same hardware
identity. Logs are bounded: gap/boot markers matter, and missing old output does
not establish that an event never occurred.

History persists in `~/.local/state/micros/shell_history` (or `$XDG_STATE_HOME`);
use `--no-history` to disable it. For scripts:

```sh
./micros shell -d NAME -c 'status --json'
./micros shell -d NAME -c 'watch --count 3 --interval 1 services'
```

Scripted execution stops on errors with nonzero status. There is no host-shell
expansion or arbitrary program execution.

## 02 · Call a service {#call-a-service}

After deploying the [counter example](write-a-service.md#declare-the-counter)
with command exposure on a supporting ESP32 base:

```text
commands
help call app.counter increment
call app.counter increment
```

Definitions come from the exact live base and confirmed application; unknown
releases or pending trials expose none. See [Service commands](service-commands.md)
for authoring, arguments, and completed/failed/unknown outcomes.

`read` and `follow` consume published ports; use their help for fields/duration.
Streaming needs a base advertising `ipc_stream: 1`. Gaps are reported, and a boot
or deployment change ends the capture; reopen it for the new lifetime.

`restart INDEX` uses the guarded [single-service restart](cli.md#stop-and-restart).
HTTP API details belong with the [server implementation](../../src/server/README.md).
