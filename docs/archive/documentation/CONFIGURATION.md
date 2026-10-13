# Application and board configuration

For new authored systems, use [composition](COMPOSITION.md): reusable service
manifests, application TOML, board wiring, and a deployment definition. Composition
emits the complete unit format described here. Existing directly authored unit
and standalone recipes remain supported. Edit the authored inputs and recompose
when a unit is generated.


Each complete [units/<device_id>.toml](../../../config/units) contains its resolved hardware and application configuration. The root [micros.toml](../../../config/micros.toml) is an example template. Unit files contain `[unit]` with `device_id` equal to the filename (12 lowercase MAC digits without separators), their own `[board]` and `[board.gpio.NAME]` wiring, and all application configuration: service identity, build sources, capabilities, tunable values, typed setting definitions and channel settings. Each service has one contiguous section with the same explicit structure: identity and `enabled`, then `config`, `config_schema`, `build`, `capabilities`, `subscriptions` and `publications`. Unused tables and lists stay empty; unused resource counts are zero. An empty `config_schema` means no configuration payload or header is generated. Actual protobuf message definitions stay under `protos/`.

## Change a setting

```toml
[services.colors.config]
brightness = 7
initial_color = "blue"

[services.button.config]
sample_interval_ms = 20
debounce_ms = 40
```

`./micros config --project units/e89f6d30e1a8.toml` validates and shows the resolved settings without contacting a device. Defaults come from `[services.NAME.config_schema.FIELD]`; `[services.NAME.config]` selects deployment values. Hardware bindings live in the same unit file. A unit without controls can use an empty `[board.gpio]` table and omit button and colors services. An optional, ignored local overlay can override values for a temporary environment:

```sh
./micros config --project units/e89f6d30e1a8.toml --overlay .micros/lab.toml
./micros deploy --overlay .micros/lab.toml
```

An overlay can contain `[services.NAME.config]` tables only. It cannot replace source paths, capabilities, channels or service versions. Direct-device profiles own addresses, certificates, tokens and their paired base. Server-backed deployment uses operator access and fetches the live base artifacts from the server. Wi-Fi credentials remain provisioned over USB into device NVS; they do not belong in these tracked TOML files. Application settings are not a secret storage mechanism.

## Generated types and delivered values

### Resource budgets

Declare the resources a service needs, without a manual handle count:

```toml
[services.button.capabilities]
gpio = ["user_button"]
# Allow two simultaneously open software timers.
timers = 2
```

micros derives the handle budget as timers + GPIO connections + publications +
subscriptions. This example needs four handles when button has one publication.
Each IPC endpoint contributes one handle, and `timers` limits simultaneously open
timers. The resolved package records the total for runtime enforcement; the current
limit is eight handles per service. Generation rejects declarations above that
limit. Remove any old `handles` field from TOML; it is no longer an authored setting.

GPIO entries refer to the hardware definition in that same unit file:

```toml
[board]
profile = "adafruit_feather_esp32_v2"
recovery_button = "user_button"

[board.gpio.user_button]
pin = 38
direction = "input"

[board.gpio.red_led]
pin = 13
direction = "output"
```

Keep one complete recipe per physical board. For composition, edit the source board
and service/application declarations, then regenerate that recipe. For a directly
authored unit, edit its `[board.gpio]` tables and service grants in place.
On graph-format-3 bases, edit the unit file and run an ordinary remote deployment:

```sh
./micros generate --project units/e89f6d30e1a8.toml
./micros deploy -d feather
```

Onboarding saves a reviewed hardware snapshot. Network builds and deployments
select the MAC-named unit file; saved application/board defaults do not override
it. Generated headers represent the last selected unit; regenerate when switching
editor targets. Standalone board files remain supported for example applications
and internal fixtures.

Services carry the complete resolved pin map and recovery input in their packages.
All packages in one application must agree. The device validates this map before
activation, stops the previous application, applies the new wiring and starts the
services. Confirmation and rollback cover the wiring and services together. A
wiring or grant change does not require a service version bump; generated pin
constants still rebuild the affected executable. This is a remote deployment with
a brief application interruption, not an in-place settings reload.

`profile` labels the physical board; it does not select a processor/toolchain.
The current original-ESP32 runtime supports zero to four named GPIO resources.
Each physical pin can appear once; flash pins, unavailable pins, resident UART
pins 1/3, and output mode on input-only pins are rejected. `recovery_button` names
an input held low at boot; an empty string disables this input. Inputs have no
internal pull configured; outputs initialize low. This is digital GPIO mapping;
peripheral-specific initialization belongs in the service driver.

`./micros generate` creates service-local `generated/NAME_resources.h` with named
functions such as `button_user_button_open(args, &state->gpio)`. Removing a grant
removes that function; runtime access is also checked. Numeric GPIO grants are
rejected. Logical line numbers follow resource-name order, so rearranging TOML
tables does not change the mapping.

Base builds retain physical flash layout and fixed runtime limits. Graph-format-2
bases require one initial USB migration to enable deployment-owned bindings.
After that, adding supported GPIO hardware, remapping pins, changing service
grants and selecting a recovery input require no base flash. Changing the kernel,
chip target, flash partition layout or fixed runtime capacity remains a base update.
Offline builds support `--firmware BASE.elf --board PATH --output DIRECTORY`.

Timers are scheduled software callbacks, independent of GPIO and hardware timer
units. `timer_open` consumes one of the declared slots; `timer_close` releases it.
Even a completed one-shot timer must be closed. Opening beyond the declared count
returns `MICROS_ERROR_CAPACITY`. Timer periods remain service configuration or code.

### Configuration payloads

For colors, `[services.colors.config_schema]` in the unit file defines a bounded unsigned brightness and named initial-color choices. Run `./micros generate --project units/e89f6d30e1a8.toml` to create `services/colors/generated/colors_config.h` in its service’s `generated/` directory. The header contains `colors_config_t`, enum constants, defaults and `colors_config_decode`. Button receives `services/button/generated/button_config.h` in the same way. Builds refresh these same files automatically. They are ignored by Git, and source includes resolve them locally for IntelliSense. Regenerate after changing configuration definitions or defaults; no firmware, compiler or device is needed. Names are service-scoped to avoid collisions when headers are used together. Never edit generated headers.

Only types, validation rules and defaults are compiled into the executable. Selected values are encoded separately: an eight-byte schema fingerprint followed by explicit little-endian uint32 fields. No raw C structs or target-dependent padding are transmitted. The prototype supports unsigned 32-bit integers and enums; strings, arrays and live updates are not implemented. Payloads are limited to 256 bytes per service. Unknown settings, out-of-range values, bad enums, wrong lengths and schema mismatches are rejected. An absent payload selects service defaults.

The selected bytes are carried in the generated package manifest's `config` field, as hex for deterministic serialization. The device graph stores the bytes alongside the service selection. Graph checksums, authenticated transfer, activation digests and immutable rollback snapshots include configuration, so restoring a deployment restores its settings too.

Before any hooks run, the runtime copies the payload into bounded instance-owned storage. ABI revision 4 introduced `args->config_data` and `args->config_bytes`, valid through `stop`. Services decode into typed arena state during `init` before acquiring hardware resources. The native decoder independently validates the payload; CLI validation is not the only check. Once started, an instance's configuration cannot be changed.

```c
micros_result_t result = colors_config_decode(
    service_args->config_data, service_args->config_bytes, &state->config);
if (result)
    return result;
configure_palette(&state->palette, &state->config);
```

Changing selected values reuses the executable when code, generated headers, compiler and base are unchanged. Packaging and deployment identity still change. A setting change does not require a service version bump; changing source or contract content does. Placement and generated GPIO-binding changes can relink the same source version, as described in [operations](OPERATIONS.md). The existing deployment mechanism restarts the whole selected graph transactionally, not just one service. Per-service configuration reloads can be considered separately.

## IPC interfaces generated from grants

`[services.colors.subscriptions.button]` generates `colors_button_open`,
`colors_button_read` and `colors_button_close` in
`services/colors/generated/colors_ipc.h`. A publication generates `open`, `publish`
and `close` instead. Channel keys come from `[channels.NAME]`; service C code does
not repeat them. Each port name must be a C identifier and unique across that
service’s publications and subscriptions.

`./micros generate` also compiles the channel's `.proto` with pinned protoc/Nanopb,
generating `.pb.h`, `.pb.c` and `.codec.h` alongside the public IPC header and its
private `*_ipc.c` implementation. Port types such as `colors_button_message_t` alias
the generated protobuf type. Publish accepts a const message pointer; read accepts
a writable message pointer and updates it only after successful decoding. Services
do not perform manual serialization.
The build automatically compiles those implementations and the vendored Nanopb runtime; do not add it to `build.sources`.
Even an empty ports section generates an empty interface, replacing old declarations.
Removing a port or its access direction makes existing calls fail compilation.
Changing a proto regenerates its representation and codecs. Changing a bound channel key regenerates the implementation and invalidates its
executable cache. Setting values still leave executable code unchanged.

The public `micros_api_t` has no callable IPC members. Generated implementations use
an opaque private SDK dispatch table, introduced in ABI revision 5. Runtime policy,
handle ownership and direction checks still enforce package grants. Native services
remain trusted code; this authoring interface is not memory isolation. Channel buffers are bounded by `max_payload`, and the schema’s maximum encoded size must fit. All protobuf fields require static storage; see the [SDK guide](SDK.md) for supported schema shapes and inline bounds. GPIO and timer
functions retain their existing API for now. The raw dispatch header under
`abi/internal/` is for generated SDK implementations, the kernel and internal tests.

## Files you review versus generated machinery

| Authored file | Purpose |
| --- | --- |
| `units/<device_id>.toml` | Hardware identity, pin wiring, flash size, project requirements, service sources/versions, capabilities, ports, settings/types/defaults, and channel contracts |
| `protos/button/v1/button_state.proto` | Existing protobuf payload definition |
| `.micros/lab.toml` (optional, local) | Environment-specific setting overrides |

The builder assigns slots in enabled-service declaration order, reads actual memory requirements from compiled descriptors, and generates hashes, packages and the binary graph. Each `[services.NAME.build]` lists sources relative to that service’s `source` directory. Channel schema paths are relative to the unit TOML file. The service alias also names its generated header and C configuration types, so treat an alias rename as a source API change. Disabling or reordering services can change slot assignment and cause relinking. The old JSON recipe format remains readable by internal tools and fixtures; the root authoring file is TOML.

Compiled working artifacts live in `.micros/build/DEVICE/`: each service has `config.bin`, generated `manifest.json`, ELF/map, memory report and executable cache. Generated headers and IPC implementation files live under `generated/` in the directory selected by `[services.NAME].source`. `resolved.json` records the expanded recipe; it is generated output, not another file to maintain. Device-specific board build requirements remain separate from service tunables: the current pixel driver still requires the 160 MHz base with dynamic frequency scaling disabled.

## Reviewing this version without touching the board

Current bases use **ABI 0 revision 6 and device graph format 3**. Use a current
base ELF and its adjacent sdkconfig for an offline review, selecting the board
through its unit file:

```sh
./micros config --project units/e89f6d30e1a8.toml
./micros build --firmware /path/to/current/micros_runtime.elf \
  --project units/e89f6d30e1a8.toml --output build/config-review
./micros build --firmware /path/to/current/micros_runtime.elf \
  --project units/e89f6d30e1a8.toml --output build/config-review --overlay .micros/lab.toml
```

Review the generated service headers, `build/config-review/board.colors/report.json`
and `build/config-review/resolved.json`. These commands build/admit packages offline.
The old `build/esp32-config/` experiment is historical and is not a current base prerequisite.

For an incompatible base, follow [onboarding](ONBOARDING.md): back up, flash, pair
its exact ELF/configuration, and redeploy the selected services. Old releases remain
associated with their original base and cannot serve as rollback targets on a new base.

## Verification

Host tests cover generated decoder defaults, bounds, malformed payloads, instance isolation, startup delivery, rejection of running-instance mutation, overlays and configuration-only version reuse. The ESP32 base and all four application services compile. Offline graph tests verify exact byte preservation, changed activation identity with identical executables, and restored identity from previous packages. Remote pin-map deployment and rollback are covered by the hardware verification in [resource insights](reviews/resource-insights.md).

Every enabled service must explicitly select its arena pool in TOML:

```toml
[services.colors.memory]
arena = "PSRAM" # or "RAM" for internal memory
stack_bytes = 4096 # optional; defaults to 4096, range 1..16384
```

The equivalent inline declaration is `memory = { arena = "RAM" }` under
`[services.NAME]`. Missing, misspelled or unsupported placement fails validation.
The hardware profile determines PSRAM availability; there is no board enable flag.
`adafruit_feather_esp32_v2` provides 2 MiB, enabled automatically by the network base
builder as a capability-only pool. Other current profiles provide none. A PSRAM
service requires both that profile capability and a PSRAM-enabled paired base.

The ESP32 application builder writes `stack_bytes` into the packaged descriptor;
changing it invalidates the executable cache. Any positive byte count up to
16384 is accepted; 4096 is a default, not a minimum. ESP32 rounds allocation
to stack-word alignment. The configured size must cover the service and runtime
call stack; validation does not prove that it is sufficient. Smaller stacks require
a base firmware built with the updated loader (older bases reject values below 4096). The standalone low-level builder
preserves the C descriptor's stack value unless `--stack-bytes` is supplied.
Service state size and alignment remain in C (`sizeof(state)` and `_Alignof(state)`);
TOML cannot override them. The current ESP32 base admits at most 16 KiB of service
stacks in total, so a larger stack may require fewer enabled services.

Channel `depth` and `max_payload` determine the allocated payload buffer:
`depth * max_payload` bytes, rounded to pointer alignment. Each buffer is allocated
in internal RAM when its channel is created and freed on channel/runtime teardown.
No allocation occurs during publish/read. Fixed channel metadata is additional.
The existing limits remain four channels, eight messages per channel, 256 bytes
per message, and an 8192-byte total payload budget; `latest` requires depth one.
The console's channel storage includes metadata and alignment padding, while
payload capacity reports the configured capacity of the active channels.

The package descriptor records placement. The runtime allocates its arena from
that pool before initialization; allocation failure does not fall back to another
pool. Stacks remain internal. Existing 4 KiB per-arena admission limits still apply.
The console reports `arena_pool` and separates PSRAM arenas from internal stacks;
private arena occupancy is not measured. Legacy packages without placement are
interpreted as their original internal-RAM format; new TOML never defaults.

The base build still targets the original ESP32
with generated 4 MiB or 8 MiB flash layouts selected by `board.flash_mb`. A different
chip still requires a compatible platform port.

[`units/b0a732c8082c.toml`](../../../config/units/b0a732c8082c.toml) describes the
USB-probed ESP32-D0WD-V3 revision 3.1 with 4 MiB flash and no user controls. Its GPIO map is empty, with no recovery input, as confirmed during the review fixes.
A board with an empty GPIO table grants no hardware access; the button/colors
application requires `user_button`, `neopixel_data` and `neopixel_power` and will be
rejected if those grants are unavailable. Inspect the file before use: its name
does not validate connected hardware, and local wiring edits can add resources.
The hardware profile does not silently disable services. Select the intended device with `-d NAME` when multiple units are online.
