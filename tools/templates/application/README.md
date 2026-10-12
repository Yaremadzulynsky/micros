# My board application

`micros new` links this project to its SDK through the ignored `.sdk` link. From this directory:

```sh
./micros compose -d host          # Validate the local host configuration
./micros generate                 # Every local service; no board needed
./micros generate --json          # Same operation, structured output
./micros test                     # Application tests under tests/
```

`AGENTS.md` gives coding agents this application's boundaries and links to the
pinned SDK's instructions through `.sdk/AGENTS.md`. Add project-specific guidance
there as your application grows.

`micros.lock` pins the SDK revision. `services/hello/service.toml` owns the reusable
implementation. `units/host.toml` is ready to run locally from the start.
New projects have no board unit or placeholder hardware ID.
Run `./micros enroll` to choose or create a server, install the board tools,
flash the board, and connect Wi-Fi. After the board is verified online,
enrollment creates `units/<hardware-id>.toml` with its detected board profile,
ESP32 flash capacity, and the hello example service. Each additional board gets
its own unit referencing the same project-owned example. Existing unit files and
service code are preserved. Enrollment does not deploy application services.

Then run the commands printed by enrollment:

```sh
./micros compose -d HARDWARE_ID       # Validate this board's unit offline
./micros deploy -d HARDWARE_ID --dry-run
./micros deploy -d HARDWARE_ID
./micros logs -d HARDWARE_ID --follow  # Expect Hello world
```

You can generate, test and run `units/host.toml` before enrolling any board.

Start by changing `config.interval_ms` under `[services.hello]` in `units/host.toml`
or your unit file. The heartbeat's `config_schema` defines the default and bounds;
its hook-based C code logs on a timer, and Micros handles lifecycle cleanup.
Run `./micros test -v`, then `./micros host deploy` and `./micros host logs` to
observe it locally. Finish with `./micros host stop`.

For a second working example, run
`./micros scaffold-service services/counter --example counter`. It demonstrates
per-instance state and typed `read`, `increment` and `reset` commands. Select it
in your application before building/deploying. See the
[service walkthrough](https://docs.meetmicros.com/site/write-a-service/).
`./micros scaffold-service services/my-service --new` creates an empty hook service.

Review application wiring in the new unit before deploying hardware services.
Enrollment detects the chip and flash, not attached peripherals.

New services declare local types, `config_schema` types/defaults/bounds, typed `pins`, timer-name
lists, interface references and commands. Units select `config` values, assign
numeric `pins`, and explicitly declare channels with the same names as service
ports. Shared interface files own delivery policy and protobuf definitions. Generated files live only under `build/`.

For an existing contract, set `build.lifecycle = "hooks"`, declare `src/service.c` in
`build.sources`, then run `./micros scaffold-service services/NAME` once. Implement
the hooks and state; generation never overwrites application code.

After declaration changes, use `./micros contract-diff services/NAME --base HEAD`
or `./micros scaffold-service services/NAME --preview --base HEAD` to review semantic
changes and only the new or changed hooks. Commit source declarations and behavior,
not generated interfaces. Device credentials remain in the user-level micros client.

Each board deploys independently. `./micros compose` selects the host before
enrollment, then the sole board. Select `-d HARDWARE_ID` when multiple boards
exist; `-d host` always validates the local host. Offline composition and host
tests do not verify physical hardware.
