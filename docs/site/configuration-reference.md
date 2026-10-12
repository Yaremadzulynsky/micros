---
title: Legacy composition
hide:
  - toc
---

<span class="docs-editorial"></span>

Reference · Legacy composition
{: .arch-eyebrow}

# Legacy composition

New projects use [authored units](declaration-authoring.md). The older
application/board/deployment format remains supported for existing projects and
multi-device composition. This page is outside the beginner path.
{: .arch-intro}

| File | Owns |
| --- | --- |
| Service manifest | Implementation and requirements |
| Application TOML | Selected services, settings, bindings, budgets |
| Board TOML | Hardware and wiring |
| Deployment TOML | Physical identities, board/application selection, connections/captures |
| Generated unit | Resolved build input for one physical device |

## 01 · Validate an existing example {#validate-an-existing-example}

From the SDK root:

```sh
./micros compose tests/fixtures/composition/deployments/dht.toml
./micros compose tests/fixtures/composition/deployments/dht.toml --output build/dht-review
```

The DHT fixture has a synthetic device ID. These commands validate declarations
offline; they do not deploy or establish that a sensor works. Read the
[fixture](../../tests/fixtures/composition/deployments/dht.toml) and its referenced
application/board files for the complete accepted syntax. The source driver has
ESP32-specific assumptions.

Use a new output directory. Generated unit paths refer to source in this checkout;
they are not frozen compiled releases. After changing inputs, recompose. For real
deployment substitute your hardware identity and wiring, then explicitly select
`--project build/dht-review/units/HARDWARE_ID.toml` from the SDK CLI.

The [greenhouse design TOML](../assets/visual-storyboard/greenhouse/applications/greenhouse.toml)
remains illustrative: its sensor/controller/display implementations are not supplied.
For runnable service code, start with [hello](get-started.md).

## 02 · Compatibility reference {#compatibility-reference}

Legacy hardware/timer declarations, explicit port bindings and
keyed channels remain readable. Avoid combining old/new definitions of the same
resource. Refer to [the loader](../../src/micros_tooling/config/configuration.py)
and [composition implementation](../../src/micros_tooling/config/composition.py)
for legacy fields rather than maintaining a second schema table here.

Current service types, budgets, and bindings have one home in
[Declarations](declaration-authoring.md). For cross-board route setup, see
[Coordination](coordination-reference.md).
