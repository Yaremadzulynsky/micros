# Offline composition fixtures

These recipes exercise service composition, local bindings, cross-device routes,
stream capture and unit identity validation. IDs `aabbccdd0001` through
`aabbccdd0004` are synthetic. No management server is configured.

`applications/`, `boards/` and `deployments/` are composition inputs. `units/`
contains independently retained expected configurations for regression comparison.
They are test data, not operator-owned or deployed applications.

From the SDK root:

```sh
./micros compose tests/fixtures/composition/deployments/dht.toml
./micros compose tests/fixtures/composition/deployments/ir.toml --json
```

These are offline commands. Create your real board units in an application
repository; never deploy these fixture identities.
