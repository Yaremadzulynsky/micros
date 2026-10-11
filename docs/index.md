---
title: Meet Micros
description: Follow a greenhouse application from native services and the shared kernel to typed channels, TOML composition, and a verified change.
hide:
  - toc
---

<p><strong>Start with the current SDK:</strong> <a href="site/get-started/#install-cli">Follow the Quickstart</a> to install the tools and create your first application. <a href="site/preview-evidence/">Historical preview evidence and limits</a> remain available for reference.</p>

<div class="visual-storyboard">

<div class="story-intro">
  <span id="develop-microcontrollers-as-services"></span>
  <span class="story-eyebrow">Meet Micros · architecture &amp; tradeoffs</span>
  <h1>One greenhouse.<br>An application you can change.</h1>
  <p>A greenhouse needs to measure its climate, control a fan, and show what is happening. Later, you will want to change how it responds.</p>
  <p>Micros makes those jobs native services that you compose into an application. The resident base provides the kernel, platform support, and management facilities that load and manage them. Application changes can follow their own update path.</p>
  <p class="story-scope">Design example: three proposed greenhouse services, used to explain Micros. The greenhouse implementation and readings below are illustrative.</p>
  <nav class="story-index" aria-label="Follow the application"><a href="#execution"><span>01</span> Kernel</a><a href="#communication"><span>02</span> Messages</a><a href="#composition"><span>03</span> Composition</a><a href="#updates"><span>04</span> Change &amp; verify</a></nav>
</div>

<section class="story-section" id="execution">
  <span id="what-you-gain-and-what-it-requires"></span><span id="know-the-boundaries"></span>
  <div class="story-section-heading"><span class="story-number">01</span><div><span class="story-eyebrow">Give each job a home</span><h2>Three services. One shared kernel.</h2></div></div>
  <p class="story-lede">Start with three jobs: Climate sensor measures conditions, Fan controller applies the ventilation policy, and Status display explains the result. Each service instance runs its lifecycle hooks and callbacks on one worker.</p>
  <figure class="story-figure" data-chart="system">
    <div class="story-figure-heading"><div><h3>One service model, across different controllers</h3><p>Shared kernel code · a separate native build for each target</p></div><span class="story-badge">Responsibilities</span></div>
    <div class="story-chart story-system" role="img" aria-label="Climate sensor, Fan controller, and Status display each have one worker. Their native service ABI connects them to the Micros kernel, which manages lifecycle, resources, channels, and supervision. A platform interface connects the shared kernel code to target-specific ESP32, SAMD21/MKR, or ESP8266 adapters. Each target requires its own build.">
      <picture class="story-fallback"><source media="(max-width: 760px)" srcset="assets/visual-storyboard/system-mobile.svg"><img src="assets/visual-storyboard/system.svg" alt=""></picture>
    </div>
    <figcaption>The kernel owns the service lifecycle and resources. A separate supervisor task within its runtime detects overdue work. The underlying platform schedules workers; ESP32 uses ESP-IDF and FreeRTOS.</figcaption>
  </figure>
  <div class="story-definitions">
    <p><strong>The service ABI connects compiled code.</strong> The Application Binary Interface defines lifecycle hooks and the kernel functions a service can call. Services compile separately; admission checks their target and ABI compatibility. The current ABI is experimental.</p>
    <p><strong>The platform interface connects the kernel to hardware.</strong> Each adapter provides tasks, time, memory, and supported hardware operations. Shared kernel source gets a target-specific build. Service binaries and required peripherals must also match the target.</p>
  </div>
  <div class="story-consequence"><span class="story-consequence-label">The tradeoff</span><p><strong>Native services have no enforced memory isolation.</strong> A fault can affect other services or management, and a stalled hook can require whole-runtime recovery.</p></div>
  <p class="story-deeper"><a href="site/service-boundaries/">Follow a service call through the ABI and platform layer →</a></p>
</section>

<section class="story-section" id="communication">
  <div class="story-section-heading"><span class="story-number">02</span><div><span class="story-eyebrow">Let the jobs work together</span><h2>The greenhouse warms. The services respond.</h2></div></div>
  <p class="story-lede">The workers now need to exchange information. Climate sensor publishes a reading. Fan controller decides whether to ventilate and publishes its own status. Status display brings both messages together.</p>
  <figure class="story-figure" data-chart="communication">
    <div class="story-figure-heading"><div><h3>Follow the information through the application</h3><p>Three services · two typed channels</p></div><span class="story-badge">Message flow</span></div>
    <div class="story-chart story-communication" role="img" aria-label="Climate sensor publishes to climate.reading. Fan controller and Status display independently read that channel. Fan controller also publishes to fan.status, which Status display reads. Both channels retain the latest state; arrows show message direction.">
      <picture class="story-fallback"><source media="(max-width: 760px)" srcset="assets/visual-storyboard/communication-mobile.svg"><img src="assets/visual-storyboard/communication.svg" alt=""></picture>
    </div>
    <p class="story-reading"><strong>Each reader advances independently.</strong> Reading a message does not remove it for another service. The display can read climate and fan status at its own pace.</p>
    <figcaption>This design uses <code>latest</code> channels: each retains the current value, so a slow display may skip intermediate states. The two messages can arrive at different times; the display should use timestamps to check their freshness.</figcaption>
  </figure>
  <div class="story-consequence"><span class="story-consequence-label">The choice</span><p><strong>Choose retention for the information.</strong> Current temperature suits a latest-value channel. A history of transitions needs a bounded stream and explicit handling of missed messages. Successful publication alone does not establish that another service acted.</p></div>
</section>

<section class="story-section" id="composition">
  <div class="story-section-heading"><span class="story-number">03</span><div><span class="story-eyebrow">Turn the design into an application</span><h2>One TOML. Three services. One application.</h2></div></div>
  <p class="story-lede">Those connections are application choices. An application TOML selects reusable service definitions, supplies settings and budgets, and binds ports to channels. Here is how the greenhouse's three jobs fit together.</p>
  <figure class="story-figure story-composition">
    <div class="story-figure-heading"><div><h3>Read the file beside the application it describes</h3><p>applications/greenhouse.toml · illustrative excerpt</p></div><span class="story-badge">Composition</span></div>
    <div class="story-code-map">
      <div class="story-code-row"><pre><code>[services.climate]
manifest = "../services/climate/service.toml"
memory = { arena = "RAM", stack_bytes = 2048 }
publications.reading = { channel = "climate" }</code></pre><div class="story-code-note"><span class="story-service-name">Climate sensor</span><p>Select the implementation and publish readings to the <code>climate</code> channel.</p></div></div>
      <div class="story-code-row"><pre><code>[services.fan]
manifest = "../services/fan/service.toml"
memory = { arena = "RAM", stack_bytes = 2048 }
<mark>config = { start_celsius = 28 }</mark>
subscriptions.reading = { channel = "climate" }
publications.status = { channel = "fan_status" }</code></pre><div class="story-code-note"><span class="story-service-name">Fan controller</span><p>Use the same reading channel, set the ventilation threshold, and publish fan status.</p></div></div>
      <div class="story-code-row"><pre><code>[services.display]
manifest = "../services/display/service.toml"
memory = { arena = "RAM", stack_bytes = 2048 }
subscriptions.reading = { channel = "climate" }
subscriptions.fan = { channel = "fan_status" }</code></pre><div class="story-code-note"><span class="story-service-name">Status display</span><p>Subscribe to both channels. The bindings match the two incoming arrows above.</p></div></div>
    </div>
    <figcaption>The channel aliases <code>climate</code> and <code>fan_status</code> refer to declarations for <code>climate.reading</code> and <code>fan.status</code>. The full design includes those declarations and schemas. The shown budgets are illustrative; implementations must be sized and validated.</figcaption>
  </figure>
  <p class="story-bridge"><strong>One file assembles existing services.</strong> Each service's manifest describes its implementation and setting schema. A board file owns wiring; a deployment selects the board, application, and device. The application file brings the software together.</p>
  <p class="story-deeper"><a href="site/compose-an-application/">Explore the complete TOML design and try offline composition →</a></p>
</section>

<section class="story-section" id="updates">
  <span id="a-shorter-development-loop"></span><span id="follow-one-change-through-the-system"></span><span id="hello-caption"></span>
  <div class="story-section-heading"><span class="story-number">04</span><div><span class="story-eyebrow">Make one useful change</span><h2>Start the fan earlier. Keep the resident base.</h2></div></div>
  <p class="story-lede">Now suppose the greenhouse should ventilate sooner. Change Fan controller's startup setting from 28°C to 26°C, then prepare a new application selection. The resident base stays in place; on the normal ESP32 service-update path, the application graph pauses for staging.</p>
  <div class="story-policy-change" aria-label="Proposed setting change: start_celsius changes from 28 to 26"><span>Fan controller · startup configuration</span><code><del>start_celsius = 28</del><b aria-hidden="true">→</b><ins>start_celsius = 26</ins></code></div>
  <figure class="story-figure" data-chart="update">
    <div class="story-figure-heading"><div><h3>Follow the changed application through deployment</h3><p>ESP32 service update · equal-width phases, not elapsed time</p></div><span class="story-badge">Behavior</span></div>
    <div class="story-controls" role="group" aria-label="Deployment outcome"><button type="button" data-choice="success" aria-pressed="true">Successful update</button><button type="button" data-choice="failure" aria-pressed="false">Failed startup</button></div>
    <div class="story-chart story-update" role="img" aria-label="Successful deployment: management stays available; all greenhouse application workers pause for staging, run as a candidate, then confirm the new graph. The prior good selection is retained until confirmation.">
      <picture class="story-fallback"><source media="(max-width: 600px)" srcset="assets/visual-storyboard/update-mobile.svg"><img src="assets/visual-storyboard/update.svg" alt=""></picture>
    </div>
    <p class="story-reading" aria-live="polite" aria-atomic="true">All three greenhouse workers pause for staging, then the candidate runs as a trial. The new selection becomes recorded good after confirmation. Resident management remains available during a normal service update.</p>
    <figcaption>Changing one service's setting still uses the application update boundary. Replacing the kernel or platform support is a separate base-firmware operation. Native faults can disrupt management too.</figcaption>
  </figure>
  <div class="story-finish" id="result">
    <span class="story-eyebrow">Close the loop</span>
    <h3>A running application is the start of verification.</h3>
    <p>After deployment, inspect service health and diagnostics. Then check the behavior you intended: with a fresh, valid reading of 27°C, a fan starting off should now turn on and the display should report it.</p>
    <div class="story-check" role="group" aria-label="Illustrative acceptance check for a fan starting off at 27 degrees Celsius">
      <div><span>Test input</span><strong>27°C</strong><small>Fresh, valid climate reading</small></div>
      <div><span>Old threshold · 28°C</span><strong>Fan stays off</strong><small>Temperature below threshold</small></div>
      <div><span>New threshold · 26°C</span><strong>Fan turns on</strong><small>Display reports the new status</small></div>
    </div>
    <p class="story-scope">Illustrative acceptance check for the proposed policy. Runtime trial confirmation establishes liveness; the fan response and display result establish application behavior.</p>
  </div>
  <p class="story-deeper"><a href="site/updates-and-recovery/">Understand rejection, failed trials, and recovery →</a></p>
</section>

<div class="story-next">
  <span id="start-with-what-you-need"></span><span id="check-the-target-before-committing"></span>
  <h2>Take this model into your own application.</h2>
  <p>Evaluate <a href="site/is-micros-a-fit/">whether Micros fits your requirements</a>, then follow the architecture or try an existing application.</p>
  <div class="story-next-links"><a href="site/compose-an-application/"><strong>Try composition locally <span aria-hidden="true">→</span></strong><span>Inspect a real sensor application without a device.</span></a><a href="site/service-boundaries/"><strong>Explore the service contract <span aria-hidden="true">→</span></strong><span>ABI, lifecycle, resource ownership, and platform support.</span></a><a href="site/get-started/"><strong>Choose your hardware <span aria-hidden="true">→</span></strong><span>Follow the setup path for your target.</span></a></div>
</div>

</div>

**Contracts behind the story:** [worker ownership and supervision](site/resources-and-failures.md), [bounded channels](site/messages-within-a-device.md), [composition](site/compose-an-application.md), and [updates and recovery](site/updates-and-recovery.md).
{: .story-sources}

- [Interactive device shell](site/interactive-shell.md): inspect services, stream logs and invoke deployed commands.
