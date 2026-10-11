# A smaller micros CLI

Status: proposed command design, not an implemented rename. The board-independent
`micros generate --service PATH` workflow is implemented now. All examples using
`service`, `project`, or `admin` below describe the proposed interface.

## Recommendation

Use seven top-level commands, with one shared command registry for the SDK and
application launcher:

```text
micros

  project   Create, validate, and test an application
  service   Define and generate reusable services
  build     Build one board's application
  deploy    Preview, deploy, and restore releases
  device    Find boards and inspect or control their running services
  shell     Open the interactive device shell
  admin     Provisioning, server, credentials, and recovery tools

Typical workflow:
  micros service generate
  micros project test
  micros deploy plan -d feather
  micros deploy -d feather
  micros shell -d feather

Use micros COMMAND --help for that workflow.
```

The current SDK has 27 parser-level commands, plus launcher commands such as
`setup`, `test`, and `sdk`. Several operations also appear under `server`.
`device list` describes local profiles while `devices` describes live boards.
`compose` means different things in an application and the SDK. Most commands
inherit platform/compiler/USB options they do not need. Application help and SDK
help are maintained separately and disagree about the normal workflow.

The proposed change consolidates those entry points and their implementations.
It preserves the capabilities; it does not simply hide an unchanged second CLI
behind a shorter help page.

## Command structure

```text
project
  new DIRECTORY                 Create an application
  check [-d DEVICE]             Validate unit declarations offline
  test                          Run the application's offline tests

service
  new NAME                      Create a reusable service contract and lifecycle
  generate [NAME|PATH]           Generate one service; omitted means all local services
  stub NAME --output FILE       Create command-handler stubs without overwriting
  show NAME                     Show declared ports, hardware, settings and commands

build -d DEVICE [--bundle DIR]   Resolve, generate adapters, build and admit one unit

deploy -d DEVICE                Build, deploy and verify one unit
  plan -d DEVICE                The same preparation, without changing the board
  history -d DEVICE             Confirmed releases and the currently selected release
  rollback -d DEVICE [--to ID]   Restore exact archived packages through normal admission
  export -d DEVICE DIR [--id ID] Export an existing immutable release

device
  list                          Live roster; `device` alone also lists it
  status -d DEVICE              Fresh runtime state
  logs -d DEVICE [--follow]      Recent logs or bounded/cancellable follow
  config -d DEVICE              The authored unit's resolved configuration, not live state
  pins -d DEVICE                Declared wiring and unused pins
  doctor -d DEVICE              Tools, identity, connectivity and compatibility checks
  restart SERVICE -d DEVICE     Restart one service, preferably by deployed name
  pause -d DEVICE               Intentionally stop the whole application
  resume -d DEVICE              Start the selected good application
  reboot -d DEVICE              Reboot the physical board

shell [-d DEVICE]               Device picker when omitted; never a firmware update

admin
  board setup ...               Existing guided onboarding phases, including explicit flash
  board base-update ...         Explicit base-firmware update and its preview
  board wifi ...                Existing USB/Wi-Fi provisioning and inspection
  server up|down|logs|console    Manage the server process and open its console
  access enroll|revoke|bind ...  Enrollment and operator access
  client profile ...            Legacy direct-device profiles, addresses and transports
  client import ...             Import existing operator configuration
  backup export|import DIR      Preserve private credentials and recovery history
  cache gc                      Prune disposable data under existing retention rules
  sdk setup ...                 Install host dependencies and optional toolchains
  legacy compose|sdk ...        Transitional expert access to old SDK-only tooling
```

`deploy` intentionally has a default action. Its positional subcommands are
unambiguous because device selection always uses `-d/--device`; a device named
`plan` is selected with `-d plan`. `deploy --dry-run` remains a compatibility alias
for `deploy plan`. There is one deployment implementation and one preparation path.

`device --help` groups its entries into **Inspect** and **Control**, with inspection
first. `deploy --help` groups **Plan/apply** and **History/restore**. Deep options
appear only on their relevant leaf command. The initial screen stays at seven
entries instead of expanding every operation.

The two new authoring conveniences, `service new` and `service show`, are small
extensions to the current scaffolding and contract reader. They are distinct from
aliases and should not be announced as available until implemented.

## Scope and defaults

- `service` operates on reusable code and `service.toml`. It never needs a board,
  enrollment, network connection, physical pin, or channel key. A service name
  resolves under `services/`; an explicit path also works.
- `project check` validates all local units by default. `-d` narrows the check.
  `project test` runs the project's offline tests once and labels them as simulated.
- `build` and `deploy` operate on exactly one unit. They generate unit adapters
  automatically; users need no extra preparation command before deployment.
- `build -d` may fetch the selected board's authenticated base and artifacts, but
  does not write to the device. An offline build requires an explicit compatible
  `--firmware` and a locally resolvable unit.
- Offline commands must not silently fetch the roster to resolve a name. Use an
  already verified cached name-to-ID mapping, or ask for the unit's hardware ID.
- `device list` always means the server's live roster. Local profiles exist only
  under `admin client profile`; no singular/plural semantic trap remains.
- `device config` and `device pins` describe authored intent and label it clearly.
  `device status` describes the actual live release. They must never substitute
  one for the other.
- `shell` always offers the device picker when `-d` is omitted. It continues to
  support status, services, commands, help and completion locally.
- `deploy` requires a selected target. In a terminal it may show the same picker;
  in scripts it requires `-d`. A previously inspected board is not an implicit
  deployment target. Each unit remains independently owned and deployed.
- Service deployment never flashes a base or provisions networking implicitly.
  Those operations belong to explicit `admin board` commands.

Use `-d/--device`, `--json`, `--project`, `--output`, and `--dry-run` consistently.
Only show options a command actually uses. In particular, status/logs should not
advertise compiler paths, build-bank selection or platform toolchain flags.
Existing transport overrides remain on relevant advanced commands; the saved
connection determines the normal route.

## What users should see

Generation reports a short summary, not thirty absolute header paths:

```text
Generated service interfaces
  button   build/services/button/generated
  colors   build/services/colors/generated
  logger   build/services/logger/generated

No board selected. Unit bindings are generated during build/deploy.
```

Detailed files are available with `--verbose` or machine-readable output.
Deployment plans lead with the actual impact: target, changed services, restart
scope, base-firmware change/no change, and resource deltas. After applying, show
whether activation was confirmed, not just whether bytes were uploaded.

A failed command should identify the operation and a useful next step:

```text
Cannot deploy: no unit for wroom (b0a732c8082c).
Create units/b0a732c8082c.toml, then run micros project check -d b0a732c8082c.
```

A lost command reply must retain the existing uncertain-outcome distinction:

```text
The request was sent, but its result is unknown. It was not retried.
Inspect the service state before issuing another command.
```

`--json` writes machine-readable output only to stdout; progress belongs on stderr.
Preserve existing JSON payloads and exit codes during alias migration. Streaming
logs remain explicitly documented JSON Lines. Avoid changing serialization as
part of a command-tree refactor.

## Complete migration map

| Existing entry point | Proposed canonical entry point |
| --- | --- |
| `new DIR` | `project new DIR` |
| Application `compose` | `project check` |
| SDK `compose SETUP` | `admin legacy compose SETUP` during migration |
| `generate --service PATH` | `service generate PATH` |
| Application `generate` | `service generate` |
| `generate -d DEVICE` | `build -d DEVICE` handles bindings; keep old generation-only alias |
| `scaffold-commands CONTRACT --output FILE` | `service stub PATH --output FILE` |
| Application `test` | `project test` |
| `build` | `build` |
| `deploy` | `deploy` |
| `plan`, `deploy --dry-run` | `deploy plan` |
| `rollback` | `deploy rollback` |
| `history` | `deploy history` |
| `release DIR` | `deploy export DIR` |
| `devices`, `server devices` | `device list` |
| `status`, `server status` | `device status` |
| `logs`, `server logs` | `device logs` |
| `config` | `device config` |
| `pins` | `device pins`; chip-only capability lookup stays an explicit expert option |
| `doctor` | `device doctor` |
| `restart INDEX` | `device restart SERVICE`; retain an explicit numeric index option |
| `stop`, `server stop` | `device pause` |
| `recover`, `server recover` | `device resume` |
| `reboot`, `server reboot` | `device reboot` |
| `shell` | `shell` |
| `init` | `admin board setup` |
| `base-update` | `admin board base-update` |
| `wifi ...` | `admin board wifi ...` |
| Legacy `device list/use/add/remove/rename/...` | `admin client profile ...` |
| `server setup/start/shutdown/console` | `admin server setup/up/down/console` |
| `server enroll/revoke/bind` | `admin access enroll/revoke/bind` |
| `server import-client` | `admin client import` |
| `server publish-base/publish-history` | `admin server publish-base/publish-history` |
| `backup export/import` | `admin backup export/import` |
| `gc` | `admin cache gc` |
| `setup [--esp32]` | `admin sdk setup [--esp32]` |
| Application `sdk COMMAND` | `admin legacy sdk COMMAND` during migration |

Keep all existing invocations working as aliases in the first release. Do not
silently reinterpret `device list`: it currently means local profiles. The new
canonical live-roster operation should initially be `device ls` until a versioned
CLI transition can resolve that collision; `devices` continues working. In the
final interface, `device list` and `device ls` can both mean the live roster.
This is an intentional compatibility exception, not two permanent data sources.

## Implementation and acceptance

1. Create one command registry with scope, accepted options, handler and help text.
   The application launcher supplies project context to that parser instead of
   intercepting and rewriting a separate command language.
2. Add canonical grouped commands backed by existing handlers. Keep compatibility
   aliases routed through the same normalized operation objects. Preserve target
   resolution, identity checks, leases, rollback and no-retry behavior.
3. Switch application templates, documentation and editor tasks to canonical
   commands. Add concise summaries and verbose detail without altering results.
4. Add service creation/inspection conveniences separately. Preserve user-owned
   files, native SDK declarations and exclusive handler scaffolding.
5. Remove aliases only in an explicitly versioned CLI transition after usage and
   script migration have been reviewed. Never remove them just to shorten help.

Acceptance checks:

- The default help shows seven workflows and useful examples; no duplicate
  server-versus-device inspection commands are promoted.
- Help is generated from the same registry in an application and the SDK.
- Offline service generation succeeds with no units, device profiles or server.
- Build/deploy handle one explicitly resolved identity; noninteractive commands
  never prompt or silently choose another board.
- Every alias in the migration table has a parser equivalence test, including
  flags, exit status and JSON output. Ambiguous old `device list` remains preserved.
- Rewiring/exposure changes leave generated service interfaces byte-identical.
- Existing native, server authentication, uncertain outcome and deployment
  regression tests pass. No runtime or base-ABI change accompanies this redesign.

The root hierarchy, option conventions and compatibility rules above are the
recommended design. The CLI rename should be its own reviewable implementation,
separate from the service-binding deployment completed in this task.
