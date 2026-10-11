# Micros documentation plan

Living plan, September 14, 2026. Primary reader, confirmed by the owner:
**someone evaluating the architecture and tradeoffs**.

Status: the five-section navigation is implemented. The greenhouse is the home
page, with a compatibility redirect from the storyboard URL. Current architecture
chapters, the local first-run/composition route, focused build guides, observation
and troubleshooting, and contract indexes are in place. Existing detailed
procedures remain the authority for setup, deployment, and exact formats.

The new local route was verified on macOS ARM64; DHT composition, recipe output,
and typed interface generation were exercised offline. This work does not add a
runnable greenhouse or claim new hardware validation. The build-out order below
remains a guide for later depth and maintenance, not a list of empty placeholder
pages. This plan supersedes earlier navigation and example proposals.

## The reader's journey

The documentation should carry a reader from **understanding one application**
to **building one**, **operating it**, and **looking up exact contracts**.
Someone evaluating Micros can follow the architectural explanations without
installing tools. Someone with a failed device can go directly to troubleshooting.

Use five main sections, in this order:

| Section | Reader's question | What belongs here |
| --- | --- | --- |
| **Start here** | What is Micros, and is it useful for my project? | The visual introduction, adoption criteria, and routes into the rest of the docs. |
| **Architecture** | How does it work, and why are the boundaries drawn this way? | Kernel, ABI, platform integration, resources, communication, updates, and design decisions. |
| **Build** | How do I make an application? | Setup, a first working application, service authoring, TOML composition, interfaces, and local testing. |
| **Operate** | How do I see, change, and recover what is running? | Console, diagnostics, deployment, recovery, connectivity, base updates, and server operations. |
| **Reference** | What is the exact rule, field, command, or limit? | CLI, SDK/ABI, TOML schemas, formats, platform details, compatibility, glossary, and contribution contracts. |

Rename the current Overview entry to **Start here** when promoting the reviewed
introduction. Retain Architecture, Build, Operate, and Reference so existing users
can recognize the navigation. Each section index offers a small number of clear
routes; do not add an index that only repeats an immediately adjacent sidebar.

## What we are keeping

The [greenhouse introduction](../site/visual-storyboard.md) is the editorial
model: purpose → kernel and platform boundaries → messages → application TOML →
a concrete setting change → deployment → behavior verification.

Keep these decisions throughout the rest of the documentation:

- The **Micros kernel** manages lifecycle, resources, channels, and supervision.
  The independent deadline supervisor is one task within its runtime.
- The service ABI and the platform interface are separate boundaries. One shared
  kernel codebase gets target-specific builds; service binaries and hardware
  requirements must match the target.
- The proposed greenhouse has Climate sensor, Fan controller, and Status display.
  Its two latest-value channels carry climate readings and fan status. The policy
  change is from 28°C to 26°C, with a fresh 27°C input used to explain verification.
- The greenhouse is a **design example**. Its TOML and schemas are documented
  artifacts, not an implemented hardware application. Runnable tutorials use
  existing, verified services until the greenhouse itself exists.
- Owner request to preserve: **“One TOML. Five services. One application,” or
  similar.** The reviewed story uses **three** to match its example. The visual
  must demonstrate application assembly, not merely state that it is easy.
  One application TOML selects existing services; manifests, board wiring, and
  deployment identity retain their separate roles.
- Board-specific memory measurements belong with their profiles and evidence.
  They are not universal introductory cost claims.
- Keep the Apex-like visual language already approved: restrained colors, clear
  labels, generous spacing, and visible explanations. Chart libraries serve the
  explanation; they do not determine the content.

## Start here

Keep this section small enough to finish before committing to a prototype.

| Page | Job and stopping point | Starting material |
| --- | --- | --- |
| **Meet Micros** | Tell the greenhouse story. End with choices to explore architecture, try composition, or choose hardware. Avoid duplicating the story on a separate overview page. | [Visual introduction](../site/visual-storyboard.md), [current home](../index.md). |
| **Is Micros a fit?** | Help evaluate independent native services, target/peripheral support, resource limits, update downtime, native fault scope, and current maturity. Use concrete fit questions and links to evidence. | [System model](../site/architecture.md), [platforms](../../src/firmware/platforms/README.md), [update boundaries](../site/updates-and-recovery.md). |

The fit page should distinguish supported, tested, experimental, and illustrative
claims. Link the canonical platform matrix instead of maintaining another copy.
“Try it” routes directly to Build; it does not begin a second setup guide here.

## Architecture

Order these as a deeper explanation of the introduction. Each chapter must also
make sense when opened from search.

| Page | Main question and boundary | Starting material |
| --- | --- | --- |
| **Kernel and service execution** | What runs on a device, who owns it, and how does service work begin and end? Explain resident base, management, service workers, lifecycle, timers, supervision, and underlying scheduling. | [System model](../site/architecture.md), [kernel overview](../../src/firmware/kernel/README.md), [worker ownership](../archive/documentation/architecture/decisions/0005-host-runtime-ownership.md). |
| **ABI and platform portability** | How can independently built services use the kernel, and how can shared kernel code support different controllers? Explain the native contract, loader compatibility, platform adapters, and source versus binary portability. | [Service boundaries](../site/service-boundaries.md), [native ABI](../../src/sdk/abi/README.md), [platform contract](../../src/firmware/contracts/include/micros/platform.h). |
| **Resources and failure boundaries** | What does the kernel reserve, own, check, and reclaim? Explain arena/stack/shared storage, handles and grants, bounded work, cleanup, and the limits of native fault containment. | [Resource discussion](../archive/documentation/architecture/resources.md), [configuration](../archive/documentation/CONFIGURATION.md), [profile measurements](../archive/documentation/architecture/flash-services.md). |
| **Messages within a device** | How do services exchange typed information? Explain publications/subscriptions, schemas, latest versus stream, independent readers, freshness, and loss. | [Bounded IPC decision](../archive/documentation/architecture/decisions/0006-bounded-ipc.md), [IPC material](../archive/documentation/architecture/ipc.md), [SDK](../archive/documentation/SDK.md). |
| **Services across devices** | What changes when information crosses a network? Explain coordination state/action/event semantics, explicit routes, optional management infrastructure, disconnection, and restart behavior. Keep ordinary captures distinct from coordination. | [Coordination](../archive/documentation/COORDINATION.md), [network bridge](../../services/network-bridge/README.md), [composition](../archive/documentation/COMPOSITION.md). |
| **Updates and recovery** | What changes, pauses, persists, and recovers? Cover application admission/staging/trials, known-good selection, configuration rollback, and the separate base-update boundary. | [Current chapter](../site/updates-and-recovery.md), [deployment](../archive/documentation/DEPLOYING.md), [base OTA](../archive/documentation/BASE_OTA.md). |
| **Why these design choices?** | Which alternatives were considered, and what consequences follow? Give short current explanations and link the dated decisions. | [Decision guide](../site/decisions.md), [ADRs](../archive/documentation/architecture/decisions/README.md), [open questions](../archive/documentation/architecture/open-questions.md). |

The first three pages separate responsibilities, interfaces, and failure costs;
do not repeat the complete system diagram in all three. The network chapter
follows local messages so it can explain the additional assumptions clearly.
Put the optional server and direct/relay paths where readers first need that
boundary, rather than assuming every application requires a server.

## Build

Teach a sequence that produces visible results. The preferred authoring route is
service manifests → application → board → deployment → reviewed build inputs.

| Page | Outcome for the reader | Starting material |
| --- | --- | --- |
| **Choose a target and set up** | Select hardware or a host, install the correct prerequisites, and complete the relevant provisioning steps. Link one maintained setup path per target. | [Get started](../site/get-started.md), [onboarding](../archive/documentation/ONBOARDING.md), [build instructions](../archive/documentation/BUILDING.md), platform READMEs. |
| **Run your first application** | Build/deploy an existing minimal example and verify its actual output. Define the expected result and common failures at each checkpoint. A host run and a board run must be clearly distinct paths. | [Hello service](../../examples/hello-service/src/service.c), [host setup](../../src/firmware/platforms/posix/README.md), [deployment](../archive/documentation/DEPLOYING.md). |
| **Compose an application with TOML** | Select services, configure settings/budgets, bind channels, identify where board/device choices belong, and inspect offline validation. Continue from the already working composition walkthrough. | [New walkthrough](../site/compose-an-application.md), [composition](../archive/documentation/COMPOSITION.md), [configuration ownership](../../config/README.md). |
| **Write a service** | Add behavior using lifecycle hooks, instance state, declared resources, error handling, and cleanup. Show a complete small example before linking every API. Explain when generated descriptors provide lifecycle plumbing. | [SDK](../archive/documentation/SDK.md), [hello manifest](../../examples/hello-service/service.toml), [generated coordination interface](../archive/documentation/COORDINATION.md#generated-service-callbacks). |
| **Connect service ports** | Define a message, declare a port, generate its typed interface, publish/read it, and observe the result. Begin locally; then show an explicit multi-device connection using an implemented example. | [SDK message material](../archive/documentation/SDK.md#data-and-messages), [composition](../archive/documentation/COMPOSITION.md), [coordination](../archive/documentation/COORDINATION.md). |
| **Add console views and controls** | Expose a real service's data and implemented commands through its console description. Show the required capture/bridge path and how to verify an action's result. | [Service interfaces](../archive/documentation/SERVICE_INTERFACES.md), [server console](../../src/server/README.md#service-interfaces). |
| **Test and diagnose locally** | Use supported host tests, simulated inputs, captures, or replay with explicit scope. Explain what each check establishes before moving to hardware. | [Build validation](../archive/documentation/BUILDING.md), [diagnostic services](../../services/diagnostics/README.md), [tests](../../tests/README.md). |

Resource declarations, hardware bindings, and settings start as focused subsections
of composition and service authoring. Split them into separate task pages only
when their size or recurring reader needs justify it. Do not require a reader to
study the native image format before their first working service.

For service authoring, reconcile the handwritten four-hook ABI with the generated
coordination wrapper's optional application hooks. Those are different authoring
layers, not contradictory requirements.

## Operate

This section begins where a runnable tutorial ends: something is on a device,
and the reader needs to understand or change it.

| Page | Outcome for the reader | Starting material |
| --- | --- | --- |
| **Find your device in the console** | Understand device identity, selected application, service state, management connectivity, and available views. Annotate a small real or explicitly simulated screen. | [Server console](../../src/server/README.md#web-console), [guide index](../site/guides.md). |
| **Observe services and diagnose problems** | Use status, logs, streams, and resource/health views to answer a concrete question. Distinguish runtime liveness, fresh data, and correct application behavior. | [Operations](../archive/documentation/OPERATIONS.md#observe-and-recover), [resource insights](../../src/server/README.md#resource-and-health-insights), [diagnostic services](../../services/diagnostics/README.md). |
| **Deploy a change and manage releases** | Review and apply an application change, select the intended project/device, verify the outcome, and preserve exact release history. | [Deployment](../archive/documentation/DEPLOYING.md), [operations](../archive/documentation/OPERATIONS.md). |
| **Troubleshoot, roll back, and recover** | Start from symptoms such as an offline device, rejected graph, missing data, failed trial, or hung service. Lead to the appropriate inspection and recovery procedure. | [Recovery behavior](../site/updates-and-recovery.md), [operations](../archive/documentation/OPERATIONS.md), [Wi-Fi](../archive/documentation/WIFI.md). |
| **Connect devices and maintain the base** | Provide focused tasks for Wi-Fi/access changes and base-firmware updates. Keep application updates and base updates as separate procedures within this group. | [Wi-Fi](../archive/documentation/WIFI.md), [base OTA](../archive/documentation/BASE_OTA.md), target setup documentation. |
| **Run the management server** | Configure the optional server, registry/relay access, backups, retention, upgrades, and recovery of operational state. | [Server](../../src/server/README.md), [package retention](../archive/documentation/DEPLOYING.md#server-artifact-retention), [repository state ownership](../../README.md#repository-map). |

Keep troubleshooting directly visible in the Operate sidebar and linked from
tutorial failure checkpoints. A reader should not need to understand every
recovery mechanism before finding the appropriate first inspection command.
Explain what can be observed through direct management and what requires the
server or a configured stream, with current target support.

## Reference

Reference is allowed to be detailed. Its job is precise retrieval, with links back
to explanations and examples. Organize it by the contract the user is looking up.

| Reference group | Contents and ownership |
| --- | --- |
| **CLI** | Commands, arguments, selection precedence, exit/error behavior, and examples. Derive mutable flags and help text from the current CLI where practical. |
| **TOML formats** | Separate service, application, board, and deployment schemas. Document defaults, required fields, validation errors, relative paths, generated outputs, and supported standalone/unit recipes. |
| **SDK and native ABI** | Function signatures, hooks, argument lifetime, ownership, result codes, generated interface conventions, ABI compatibility, and C/C++ constraints. Keep version facts canonical. |
| **Messages and protocols** | Protobuf restrictions, local channel contracts, coordination semantics, management/transport formats, and console-description schema. Separate schema reference from authoring tutorials. |
| **Packages, loading, and storage** | Native images, package identity, base/layout compatibility, activation records, resource limits, and profile-specific RAM/flash measurements. |
| **Platforms and verified support** | One capability matrix linked to target profiles, supported peripherals/transports, setup paths, fixed limits, and dated validation evidence. Distinguish implementation from hardware verification. |
| **Glossary and contributing** | Definitions of service, kernel, base, application graph, channel, board, deployment, and release; repository guide, building/testing Micros, adding a platform, and contributing documentation. |

Group headings can contain multiple reference pages, but do not expose every
field or function as a sidebar entry. Keep the exact contract in one location:
a tutorial should link its field reference, not copy the entire schema.

Keep dated milestones, historical architecture, review reports, and superseded
decisions under a clearly labeled history/evidence collection reached from
Reference and relevant current chapters. Current supported behavior must never
depend on reconstructing a sequence of milestone resolutions.

## Routes through the sections

| Reader | Recommended route |
| --- | --- |
| Architecture evaluator | Meet Micros → Is Micros a fit? → relevant Architecture chapters → platform support and evidence. |
| First-time application author | Meet Micros → choose a target → first running application → compose TOML → write/connect services → verify in Operate. |
| Reader without hardware | Meet Micros → offline composition → supported host example or simulated console → target setup when ready. |
| Device operator | Console/observation → deploy or troubleshoot → exact commands and target-specific recovery rules. |
| Kernel/platform contributor | ABI/platform chapter → platform reference → repository and build/test guidance. |

Every chapter should end with one natural continuation and one exact-reference
link. Limit side trips during the main explanation. Network/distributed examples
may use the existing IR application after the local service model is established;
do not silently turn the hypothetical greenhouse into verified hardware evidence.

## Visuals and page rhythm

Carry the approved visual language into the rest of the docs, but choose each
visual according to the question it answers.

| Where | Visual and purpose |
| --- | --- |
| Introduction | Keep the connected greenhouse figures and TOML-to-service mapping already reviewed. |
| Kernel/execution | A focused lifecycle or ownership diagram only where it adds detail beyond the introduction. |
| ABI/platform chapter | Trace one real call from service API table through the kernel to its platform operation; show compatibility checks beside the loading boundary. |
| Local messages | Compare latest-value and bounded-stream retention with a short sequence of publications and reads. |
| Across devices | Add the device/network boundary and show disconnect/restart consequences using an implemented example. |
| TOML authoring | Pair short declarations with the services, bindings, or validation result they create. |
| Deploy/recover | Reuse the update timeline semantics; add a compact outcome table for exceptional paths. |
| Observe/console | Use small annotated captures that show where to inspect one fact. Label simulation or recorded evidence explicitly. |
| Platform/resources | Use a comparison table first. Plot actual measurements only when the board, build profile, units, and measurement method are available. |

An explanatory page starts with its answer, develops one mechanism or example,
states the relevant tradeoff at that point, and offers the next step. A tutorial
starts with its outcome and prerequisites, gives actions and expected results,
and includes useful failure checkpoints. Reference uses definitions and tables.

Keep essential meaning visible without hover, animation, or JavaScript. Use
interaction when changing a scenario teaches something consequential, as with
successful versus failed activation. Avoid repeated architecture diagrams,
decorative charts, screenshot-based code samples, and large collections of cards.

## Content migration and consistency work

Reuse the current material, but separate its responsibilities:

| Existing material | Planned treatment |
| --- | --- |
| Home and visual storyboard | Promote the reviewed story to the front door; preserve the storyboard URL/anchors as an alias or redirect. |
| System model and service-boundaries chapter | Establish canonical execution and ABI/platform explanations; remove duplicated introductions. |
| SDK | Split runnable authoring guidance from the exact SDK/ABI contract. Reconcile manual descriptors and generated coordination wrappers. |
| Configuration, composition, and repository ownership | Lead new applications through composition. Clearly retain standalone/unit recipes as supported alternatives. Resolve conflicting “which file do I edit?” instructions. |
| Build and onboarding | Separate target setup, first application, contributor builds, migration, and historical validation. |
| Deployment, operations, and base OTA | Separate architectural behavior, task procedures, protocol details, and profile measurements. Preserve recovery exceptions. |
| Server README and service interfaces | Extract console user guidance, view authoring, server administration, and protocol/reference material into their proper sections. |
| Coordination and service diagnostics | Separate concepts, working integration tasks, exact semantics, and dated evidence. |
| Historical architecture, V1, milestones, and reviews | Retain as labeled evidence/history; link current explanations instead of treating historical proposals as present support. |

Before moving authoritative reference text, verify version and support claims
against current headers, code, and scoped evidence. The current source material
mixes old ABI revisions, authored unit recipes, newer composition, and multiple
lifecycle authoring layers. Navigation changes alone do not resolve those issues.

Preserve existing URLs and important anchors with useful retained pages or
redirects. Verify moved links, search results, downloads, and code examples.
Do not alter unrelated application, server, or hardware work while restructuring
documentation.

## Build-out order

1. **Set the reading paths.** Review this section map, promote the introduction,
   and write the compact fit page. Keep links into working current guides.
2. **Finish the main architectural account.** Reconcile src/firmware/kernel/execution,
   ABI/platforms, resources/failure boundaries, local messages, and update behavior.
3. **Make the first developer route complete.** Choose/setup → first working
   example → TOML composition → a small service → observe the result. Execute
   commands in their stated scope before presenting the route as runnable.
4. **Complete operation and integration.** Add console/diagnostics, application
   changes, symptom-led troubleshooting, networking/base tasks, server operations,
   and multi-device authoring with their current support conditions.
5. **Consolidate exact reference and history.** Extract canonical schemas and
   contracts, move historical authority out of current explanations, and validate
   the whole navigation/search/link structure.

Deliver reviewable routes, not batches of disconnected chapters. Reference needed
by a route must be available when that route ships; final consolidation is not a
reason to leave current links broken.

## Acceptance criteria

A new evaluator can explain what Micros adds, where the kernel sits, how service
and platform compatibility work, what changes during deployment, and which
constraints matter for their hardware.

An author can identify the file to edit, build a small application, publish/read a
typed message, and verify a real result without studying a binary format first.

An operator can find an offline device, failed deployment, missing reading, or
rollback procedure directly from Operate.

No chapter implies that managed native services are memory-isolated, that one
binary runs on every controller, that all targets have identical features, that
a one-service change avoids graph staging, or that liveness proves correct
application behavior.

Verification includes strict MkDocs builds, valid links and preserved anchors,
desktop/mobile visual review, keyboard and fallback behavior for interactive
figures, and scoped execution of tutorial commands. This excluded planning
document alone does not require a site build or hardware activity.


## Implementation checkpoint — September 14, 2026

The published structure now follows the five sections above. The home is the
single canonical greenhouse introduction; the former storyboard URL redirects
with its query and fragment preserved. Historical home and architecture anchors
remain available. The setup, service-authoring, and operations entry points now
link to current explanations and existing detailed contracts.

Validation performed for this implementation:

- Strict MkDocs production build and generated-site link/asset/anchor audit.
- Isolated host configure/build of `micros-control` and `package_minimal_c` in
  `build/docs-first-app`, followed by `hello_serial_timer`: passed on macOS ARM64.
- DHT and IR deployment composition previews: passed offline.
- DHT recipe emission, resolved settings inspection, and generated typed
  interfaces: passed. The DHT's empty settings object is explained in the guide.
- Browser review of the home, Build navigation, first-run page, and troubleshooting;
  layout checks at 320, 390, 780, and 1280 pixels showed no page overflow.
- Old storyboard `#updates` URL preserved its section on the new home; keyboard
  failure/success controls hid/restored the illustrative acceptance result.
- Compatibility redirects are excluded from search to keep one introduction.

No new physical hardware evidence was produced by this documentation work.
The practical walkthrough uses existing implementations; the greenhouse remains
an illustrative design. Deeper target procedures and historical evidence remain
linked rather than copied into competing guides.


## Temporary archive — September 14, 2026

Owner direction: move all older documentation out of the live site for now.
The legacy root manuals, earlier architecture and decisions, milestone records,
review/evidence files, and unused explainer scripts/styles now live under
`docs/archive/documentation/`. New editorial pages remain under `docs/site/`, with
the greenhouse at `docs/index.md`. This current plan lives in `docs/planning/`
and is excluded from publication.

The five navigation sections now include only the new pages. Legacy detailed
procedures are available through corrected archive links where the new pages
still depend on them; the old documents are not published or indexed by search.
`docs/archive/documentation/relocations.json` records the move for a later restoration
or selective rewrite. No manual, report, or captured evidence was deleted.


## Current documentation stands alone — September 14, 2026

The user rejected archive links as a substitute for the new documentation. This
supersedes the temporary archive-link approach above. Keep the approved visual
introduction as the front door, then connect focused explanations, complete tasks,
and compact contracts. Historical content stays preserved outside publication.

Implemented in this pass:

- Replaced every published archive exit with current guidance, including the
  design rationale and platform/evidence explanation.
- Added ESP32 hello setup, application deployment/rollback, device maintenance,
  and base-update tasks, with outcomes and relevant failure checkpoints.
- Added focused configuration, service API, coordination, console metadata, and
  package/storage contracts. Retained implementation source links for exact code.
- Completed the explicit device-ID composition path for first-board deployment;
  included editable host-tool installation for the reorganized src layout.
- Updated navigation and links for config/ and src/ while another task reorganized
  the repository. Corrected the CLI bootstrap entry-point path left by that move.
- Excluded docs/archive/ from the site and added a generated-HTML check that rejects
  archive links, including raw HTML and external repository URLs.
- Preserved the existing visual language; kept table field names readable on
  narrow screens with horizontal scrolling confined to the table wrapper.

Validation: strict MkDocs build; 36 generated HTML pages; 2,445 local links/assets
and anchors with no errors or archive exits; 156 current search entries. DHT and
IR composition previews passed offline. The new hello application composed with
an isolated synthetic device ID. Existing waveform metadata and the illustrative
command form passed the production validator. A fresh macOS ARM64 build and
hello_serial_timer check passed after the source move. No boards were contacted
or changed, and no new physical-hardware result is claimed.
