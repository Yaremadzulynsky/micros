# Typed command service

This counter shows command declarations, user-owned C handlers and generated
request/reply dispatch without hand-written protobuf or presentation metadata.

- `service.toml` declares `get_value` and `set_value` (0–100).
- `src/commands.c` implements the handlers.
- `src/service.c` integrates generated open/step/close lifecycle helpers.
- `micros.toml` explicitly exposes both commands and lets the SDK add the bridge.

Generate from the SDK root:

```sh
./micros generate --service examples/typed-commands
```

The recipe is a reference, not a declaration for an enrolled physical board. To
use it in an application, copy the service into `services/` and add its selection
to the chosen board's unit. Build/deploy that unit normally; commands use its
deployed service name:

```text
feather> call example.counter set_value value=42
feather> call example.counter get_value
```

Read the [service command guide](../../docs/site/service-commands.md) for supported
types, scaffolding, limits and completion/error semantics. The older
[shell-service example](../shell-service/README.md) demonstrates numeric queued
console forms and telemetry views, which remain supported.
