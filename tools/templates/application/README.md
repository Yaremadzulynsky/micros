# Simulated climate application

Three services and two typed, latest-value channels run on one host or board.
Everything is simulated: no sensors, GPIO, buttons, fan, display or external input
is required. The status display writes diagnostic logs.

```text
climate-sensor ── climate_reading ──┬── fan-controller ── fan_status ──┐
                                  └──────────────────────────────────┤
                                                               status-display
```

- `services/climate-sensor/` calls the separate `src/simulated_sensor.c` driver
  every second. The deterministic temperature cycle is 20, 22, 24, 26, 28, 30,
  28, 26, 24, 22 °C; simulated humidity varies from 45 to 50 percent.
- `services/fan-controller/` subscribes to readings and applies hysteresis: on at
  or above 28 °C, off at or below 24 °C, retaining its state between thresholds.
  It publishes a simulated fan decision for every received sample.
- `services/status-display/` independently subscribes to both channels. It logs
  matching sample IDs and timestamps, and reports stale data after five seconds.
  Latest channels can skip intermediate samples; the two reads are not atomic.
- `protos/climate/` and `protos/fan/` own the protobuf messages and delivery policy.
  Fixed-size integer fields keep messages bounded; no floating-point formatting
  or strings are needed in the messages.

## Run locally

`micros new` creates `.sdk`, an ignored dependency link, and `micros.lock`, the
exact SDK revision. Run commands from this application directory:

```sh
./micros compose -d host
./micros generate
./micros test -v
./micros host deploy
./micros host logs
./micros host stop
```

Expect lines such as:

```text
Simulated climate #5: temp=28000 mC humidity=490 permille fan=ON
Simulated climate #8: temp=26000 mC humidity=480 permille fan=ON
Simulated climate #9: temp=24000 mC humidity=470 permille fan=OFF
```

`28000 mC` is 28 °C; `490 permille` is 49% relative humidity. These are generated
values and policy decisions, not physical measurements or actuator feedback.
The tests compile the real services, generated lifecycle and protobuf codecs
with a deterministic clock and test bus. They do not verify board hardware.

## Deploy to a board

Run `./micros enroll`. After confirming the board online, enrollment creates
`units/<hardware-id>.toml` with the detected board and this three-service graph.
It also installs the SDK's pristine simulated climate starter through the server
and waits for confirmation. Existing units and service code are preserved; your
edits are deployed only when you request an update. Use `--no-starter` for a
management-only board. Inspect what enrollment already installed:

```sh
./micros status -d HARDWARE_ID
./micros logs -d HARDWARE_ID --follow
```

After editing this board's unit or services, preview and deploy the change:

```sh
./micros compose -d HARDWARE_ID
./micros deploy -d HARDWARE_ID --dry-run
./micros deploy -d HARDWARE_ID
```

Each board deploys independently. Select `-d HARDWARE_ID` when multiple boards
exist. `-d host` selects the host configuration. Enrollment supplies target stack
budgets; inspect live headroom when adding behavior. Credentials and recovery
state remain outside tracked source.

## First changes

Change `services.fan_controller.config.on_millicelsius` to `26000` in your unit,
keeping `off_millicelsius` lower. Redeploy and observe the fan turn on earlier.
Change `services.climate_sensor.config.interval_ms` to adjust sampling; set the
status display's `stale_after_ms` above the interval. The service contracts own
setting types, defaults and bounds; unit files select values.

Host packages are immutable by name/version: bump the changed service's version
before reinstalling changed code or settings on the host. Board releases use
content hashes. Later, replace the simulated driver with a real hardware driver
while retaining the message contract and downstream services.

See the [configuration reference](https://docs.meetmicros.com/site/declaration-authoring/),
[service declarations](https://docs.meetmicros.com/site/service-configuration/) and
[typed channels](https://docs.meetmicros.com/site/connect-service-ports/).
`AGENTS.md` links the matching SDK guidance. Generated output belongs under `build/`.
Use `./micros scaffold-service services/my-service --new` for another service,
or `--example counter` for a typed-command example.
