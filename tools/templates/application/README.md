# My board application

`micros new` links this project to its SDK through the ignored `.sdk` link. From this directory:

```sh
./micros generate                 # Every local service; no board needed
./micros generate --json          # Same operation, structured output
./micros compose                  # Validate the single unit offline
./micros test                     # Application tests under tests/
```

`micros.lock` pins the SDK revision. `services/hello/service.toml` owns the reusable
implementation; `units/000000000000.toml` owns this board's identity, wiring,
settings and memory allocation. Run `./micros enroll` to choose or create a server,
install the board tools, flash the board, and connect Wi-Fi. After success, an
unchanged starter for the same platform receives the board ID and detected ESP32
flash capacity automatically; the original placeholder is saved under
`build/enrollment/`. The command prints the deployment preview to run next.

Start by changing `config.interval_ms` under `[services.hello]` in `host.toml`
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

If you have customized the unit, replace the placeholder ID and filename together
and select the correct board profile before building or deploying. Enrollment
preserves customized units and does not deploy application services.

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

Each board deploys independently. Select `-d HARDWARE_ID` when multiple unit files
exist. Offline composition and host tests do not verify physical hardware.
