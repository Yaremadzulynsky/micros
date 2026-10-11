# AI workflow skills

These are repository-local LLM skills: each folder contains a `SKILL.md` with
discovery metadata and operational instructions grounded in micros commands,
service contracts and hardware constraints.

| Skill | Example request |
| --- | --- |
| [micros-device-access](micros-device-access/SKILL.md) | “Check the Feather and find what's wrong.” Starts a bounded health survey even without a named symptom. |
| [micros-diagnostic-services](micros-diagnostic-services/SKILL.md) | “Deploy the DHT diagnostic on my wired Feather and verify its readings.” |
| [micros-pin-graphs](micros-pin-graphs/SKILL.md) | “Capture the existing temperature readings for a minute and graph them.” |
| [micros-diagnose-missing-data](micros-diagnose-missing-data/SKILL.md) | “Find where these sensor messages stop reaching the consumer.” |
| [micros-diagnose-signal-quality](micros-diagnose-signal-quality/SKILL.md) | “Capture the input around a transition and explain its gaps or noise.” |
| [micros-diagnose-with-replay](micros-diagnose-with-replay/SKILL.md) | “Replace the producer with controlled inputs to reproduce this processing fault.” |
| [micros-diagnose-system](micros-diagnose-system/SKILL.md) | “The services are running but something is broken. Find the failing path.” |

The root [AGENTS.md](../../AGENTS.md) directs agents to read the device-access and
system-diagnosis skills for board investigations, then select specialized skills
as needed. Agents that do not load `AGENTS.md` can be directed to the relevant
`tools/skills/<name>/SKILL.md` explicitly. This folder does not install skills globally.
Keep the checkout available because the skills link to its maintained documentation
and source. Run application CLI commands from your application directory. When
working from the SDK root instead, pass `--project PATH/TO/UNIT.toml` to source
plan/build/deploy commands. SDK helper scripts use the checkout-relative paths
shown in their references.

Start general board investigations with `micros-device-access`. It maps the live
application, compares progress over a bounded window, captures existing data and
routes concrete findings to the specialized skills. Its capture-access reference
distinguishes login, operator-route, metadata and firmware-capability failures.
The survey routes to `micros-diagnose-system` for functional tests: model the path,
form competing explanations, choose a discriminating experiment, update the
diagnosis and verify the correction. It selects the probe, recorder, replay or
existing service interfaces according to the question; worked examples illustrate
the process without prescribing a hardware-specific diagnosis. Agents must also
complete missing prerequisites for authorized tests, including compatible
coordination routes, then trigger fresh work and verify its outcome. Route setup
preserves unrelated connections and does not replace functional testing.

Device inspection and service deployment use the existing CLI. Charts require
actual exported measurements and a plotting tool in the agent's environment.
The [diagnostic service library](../../services/diagnostics/README.md) implements
channel observation, bounded input capture and controlled replay on the device.
Skills select those instruments and interpret their evidence; host helpers collect
results through the existing server. Pin/ADC support is constrained by the actual
platform, grants and sampling limits. Adding skills does not itself change a device.

A concise description for sharing the project:

> micros includes an AI-first embedded workflow: repository-local agent skills
> guide device inspection, diagnostic service deployment, and plotting captured
> measurements using the same CLI and native service contracts as a developer.

The skills encode the workflow; live hardware results still need to be demonstrated.
