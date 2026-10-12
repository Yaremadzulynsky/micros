---
title: Native services. One shared runtime.
hide:
  - toc
---

<span class="docs-editorial"></span>

Start · Native services. One shared runtime.
{: .arch-eyebrow}

# Native services. One shared runtime.

Micros separates application behavior from the resident base that loads and manages
it. Each native service has its own worker, state, and declared resources; all
services share the device's address space.
{: .arch-intro}

## 01 · What runs on the device {#what-runs-on-the-device}

<figure class="arch-system">
  <div class="arch-diagram-label">Application · simulated climate starter</div>
  <div class="arch-workers"><div><strong>Climate sensor</strong><span>Generate readings</span><small>One worker</small></div><div><strong>Fan controller</strong><span>Apply ventilation policy</span><small>One worker</small></div><div><strong>Status display</strong><span>Explain the result</span><small>One worker</small></div></div>
  <div class="arch-connector">↕ Native service ABI</div>
  <div class="arch-base"><div class="arch-diagram-label">Resident base</div><strong>Micros kernel</strong><p>Lifecycle · owned resources · channels · supervision</p><div class="arch-foundation"><span>Platform integration<br><small>Tasks, time, memory &amp; hardware</small></span><span>Enabled management<br><small>Inspect &amp; deploy from host tools</small></span></div></div>
  <div class="arch-connector">↕ Platform facilities</div>
  <div class="arch-hardware">Controller &amp; peripherals</div>
  <figcaption>Responsibilities, not memory partitions. The starter generates readings and logs fan decisions without external hardware. All native services share the device's address space.</figcaption>
</figure>

The base contains the kernel, platform integration, and enabled management.
On ESP32, ESP-IDF and FreeRTOS provide underlying tasks and scheduling. Micros
adds service ownership, lifecycle, channels, and independent deadline supervision.
The same kernel source is built for each target; drivers and native binaries
still depend on the target and base.

The source follows the same boundary:
[kernel/](../../src/firmware/kernel/README.md) owns execution and supervision;
[controller/](../../src/firmware/controller/) owns application lifecycle,
deployment, rollback and reporting; and
[platforms/](../../src/firmware/platforms/) implements hardware, storage and
transport contracts. Every target uses the same shared controller and deployment
record. Capability declarations reject explicitly required unsupported features
at compile time. The [platform contract map](../../src/firmware/contracts/README.md)
defines what a new platform must implement and how to check it.

Independently deployed diagnostic packages live in [services/](../../services/README.md),
and reference applications in [examples/](../../examples/README.md). They use the
[public service SDK](../../src/sdk/README.md). The CLI and management server share
[host tooling](../../src/micros_tooling/README.md); the
[server](../../src/server/README.md) owns its browser console. Use the
[repository map](contributing.md#repository-map) to find each component's source.

## 02 · Follow a service lifetime {#follow-a-service-lifetime}

| Stage | Service | Kernel |
| --- | --- | --- |
| Admission | Supplies its native descriptor and requirements | Checks compatibility and capacity |
| Initialization | Establishes state | Supplies zeroed arena, context, and API table |
| Start/work | Performs bounded hooks and callbacks | Serializes the instance's work on its worker |
| Stop | Releases application-owned resources | Waits for quiescence before reclaiming memory |

Generated hook services delegate resource plumbing to generated code. The
[Service API](service-api.md) defines exact lifecycle, memory, and error rules;
[Write a service](write-a-service.md) implements a small example.

## 03 · Pass messages {#pass-messages}

In the simulated climate starter, the sensor publishes climate readings and the fan
controller and display read independently. A latest-value channel retains current
state; a bounded stream retains a limited sequence. Neither removes the need to
handle stale or missing readings.

Use [Connect services](connect-service-ports.md) for the declaration and retention
rules. Across boards, [Coordination](coordination-reference.md) distinguishes state,
actions with outcomes, and transient events.

## 04 · Change behavior {#change-behavior}

A service or setting update can retain the resident base. Compatible selective
updates on supporting bases preserve unchanged peers; shared-layout changes and
unsupported bases require whole-application activation. The
[deployment plan](deploy-an-application.md#what-restarts) reports the scope.

A candidate trial checks liveness before recording a good selection. Runtime
confirmation is not a physical acceptance test. For the greenhouse's threshold
change from 28°C to 26°C, a fresh 26°C reading with the fan initially off would
distinguish the two policies. The starter can test this policy without a physical fan; wired hardware needs
separate verification.

## 05 · Essential limits {#essential-limits}

- **Trusted native code:** ownership checks do not isolate memory. A bad write can
  affect peers, kernel, or management.
- **Bounded resources:** each worker consumes stack/state; channels can overflow.
  The selected base can impose tighter limits than the declaration format.
- **Recovery, not hard real time:** a worker that cannot stop may require device
  recovery. Detecting a deadline miss does not make its memory safe to reuse.
- **Source portability:** rebuild for the target, ABI, and exact base; a board
  definition cannot supply a missing driver.

[Quickstart](get-started.md) runs all three services locally.
[Packages and compatibility](packages-and-storage.md) explains artifacts and base
matching; the [glossary](glossary.md) defines terms used in the references.
