---
title: Meet Micros
description: Follow a greenhouse application from native services and the shared kernel to typed channels, TOML composition, and a verified change.
hide:
  - toc
---


<div class="visual-storyboard">

<div class="story-intro">
  <span id="develop-microcontrollers-as-services"></span>
  <span class="story-eyebrow">Meet Micros · architecture &amp; tradeoffs</span>
  <h1>One greenhouse.<br>An application you can change.</h1>
  <p>A greenhouse needs to measure its climate, control a fan, and show what is happening. Later, you will want to change how it responds.</p>
  <p>Micros makes those jobs native services that you compose into an application. The resident base provides the kernel, platform support, and management facilities that load and manage them. Application changes can follow their own update path.</p>
  <p class="story-scope">The Quickstart implements this flow with a simulated sensor driver, a fan decision and a log display. No greenhouse hardware is required; actual sensors and actuators need their own drivers and wiring.</p>
  <nav class="story-index" aria-label="Follow the application"><a href="#execution"><span>01</span> Kernel</a><a href="#communication"><span>02</span> Messages</a><a href="#composition"><span>03</span> Composition</a><a href="#updates"><span>04</span> Change &amp; verify</a></nav>
</div>

<section class="story-section" id="execution">
  <span id="what-you-gain-and-what-it-requires"></span><span id="know-the-boundaries"></span>
  <div class="story-section-heading"><span class="story-number">01</span><div><span class="story-eyebrow">Give each job a home</span><h2>Three services. One shared kernel.</h2></div></div>
  <p class="story-lede">Start with three jobs: Climate sensor generates temperature and humidity, Fan controller applies the ventilation policy, and Status display explains the result. Each service instance runs its lifecycle hooks and callbacks on one worker.</p>
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
    <div class="story-chart story-communication" role="img" aria-label="Climate sensor publishes to climate_reading. Fan controller and Status display independently read that channel. Fan controller also publishes to fan_status, which Status display reads. Both channels retain the latest state; arrows show message direction.">
      <picture class="story-fallback"><source media="(max-width: 760px)" srcset="assets/visual-storyboard/communication-mobile.svg"><img src="assets/visual-storyboard/communication.svg" alt=""></picture>
    </div>
    <p class="story-reading"><strong>Each reader advances independently.</strong> Reading a message does not remove it for another service. The display can read climate and fan status at its own pace.</p>
    <figcaption>This design uses <code>latest</code> channels: each retains the current value, so a slow display may skip intermediate states. The two messages can arrive at different times; the display should use timestamps to check their freshness.</figcaption>
  </figure>
  <div class="story-consequence"><span class="story-consequence-label">The choice</span><p><strong>Choose retention for the information.</strong> Current temperature suits a latest-value channel. A history of transitions needs a bounded stream and explicit handling of missed messages. Successful publication alone does not establish that another service acted.</p></div>
</section>

<section class="story-section" id="composition">
  <div class="story-section-heading"><span class="story-number">03</span><div><span class="story-eyebrow">Turn the design into an application</span><h2>One TOML. Three services. One application.</h2></div></div>
  <p class="story-lede">Those connections are application choices. A unit TOML selects services, supplies settings and budgets, and declares the channels their same-name ports use. Here is how the greenhouse's three jobs fit together.</p>
  <figure class="story-figure story-composition">
    <div class="story-figure-heading"><div><h3>Read the file beside the application it describes</h3><p>units/host.toml · starter excerpt</p></div><span class="story-badge">Composition</span></div>
    <div class="story-code-map">
      <div class="story-code-row"><pre><code>[services.climate_sensor]
source = "../services/climate-sensor"
contract = "service.toml"
memory = { arena = "RAM", stack_bytes = 4096 }</code></pre><div class="story-code-note"><span class="story-service-name">Climate sensor</span><p>Select the implementation. Its contract publishes through a <code>climate_reading</code> port.</p></div></div>
      <div class="story-code-row"><pre><code>[services.fan_controller]
source = "../services/fan-controller"
contract = "service.toml"
memory = { arena = "RAM", stack_bytes = 4096 }
<mark>config = { on_millicelsius = 28000, off_millicelsius = 24000 }</mark></code></pre><div class="story-code-note"><span class="story-service-name">Fan controller</span><p>Set the ventilation threshold. Its contract subscribes to <code>climate_reading</code> and publishes <code>fan_status</code>.</p></div></div>
      <div class="story-code-row"><pre><code>[services.status_display]
source = "../services/status-display"
contract = "service.toml"
memory = { arena = "RAM", stack_bytes = 4096 }</code></pre><div class="story-code-note"><span class="story-service-name">Status display</span><p>Its contract subscribes to both <code>climate_reading</code> and <code>fan_status</code>, matching the two incoming arrows above.</p></div></div>
      <div class="story-code-row"><pre><code>[channels.climate_reading]
[channels.fan_status]</code></pre><div class="story-code-note"><span class="story-service-name">Shared channels</span><p>Same-name ports attach to these channels. Each shared interface supplies the message schema and delivery policy.</p></div></div>
    </div>
    <figcaption>The <code>climate_reading</code> and <code>fan_status</code> channels carry the climate reading and fan status shown above. This host excerpt uses the real starter sources. Enrollment adds the actual board identity and selects target-specific stack budgets; retain those budgets for MKR and ESP8266.</figcaption>
  </figure>
  <p class="story-bridge"><strong>One unit selects an application's services for a device.</strong> Each <code>service.toml</code> owns reusable behavior and interfaces. The unit owns hardware identity, board settings, wiring, service selection and budgets.</p>
  <p class="story-deeper"><a href="site/declaration-authoring/">Explore service contracts and authored units →</a></p>
</section>

<section class="story-section" id="updates">
  <span id="a-shorter-development-loop"></span><span id="follow-one-change-through-the-system"></span><span id="hello-caption"></span>
  <div class="story-section-heading"><span class="story-number">04</span><div><span class="story-eyebrow">Make one useful change</span><h2>Start the fan earlier. Keep the resident base.</h2></div></div>
  <p class="story-lede">Now suppose the greenhouse should ventilate sooner. Change Fan controller's startup setting from 28°C to 26°C, then prepare a new application selection. The resident base stays in place. Compatible updates on supporting ESP32 bases preserve unchanged service instances; other changes use the whole-application path shown below.</p>
  <div class="story-policy-change" aria-label="Setting change: on_millicelsius changes from 28000 to 26000"><span>Fan controller · startup configuration</span><code><del>on_millicelsius = 28000</del><b aria-hidden="true">→</b><ins>on_millicelsius = 26000</ins></code></div>
  <figure class="story-figure" data-chart="update">
    <div class="story-figure-heading"><div><h3>Follow the changed application through deployment</h3><p>Whole-application example · equal-width phases, not elapsed time</p></div><span class="story-badge">Behavior</span></div>
    <div class="story-controls" role="group" aria-label="Deployment outcome"><button type="button" data-choice="success" aria-pressed="true">Successful update</button><button type="button" data-choice="failure" aria-pressed="false">Failed startup</button></div>
    <div class="story-chart story-update" role="img" aria-label="Successful deployment: management stays available; all greenhouse application workers pause for staging, run as a candidate, then confirm the new graph. The prior good selection is retained until confirmation.">
      <picture class="story-fallback"><source media="(max-width: 600px)" srcset="assets/visual-storyboard/update-mobile.svg"><img src="assets/visual-storyboard/update.svg" alt=""></picture>
    </div>
    <p class="story-reading" aria-live="polite" aria-atomic="true">All three greenhouse workers pause for staging, then the candidate runs as a trial. The new selection becomes recorded good after confirmation. Resident management remains available during a normal service update.</p>
    <figcaption>Transfer and restart scope differ: the current ESP32 deploy sends all application service images and the complete configuration. Selective reloads preserve compatible peers, with brief pauses at hook boundaries. <a href="site/deploy-an-application/#what-restarts">Check the deployment plan for restart scope.</a> Replacing the kernel or platform is a separate base update; native faults can disrupt management too.</figcaption>
  </figure>
  <div class="story-finish" id="result">
    <span class="story-eyebrow">Close the loop</span>
    <h3>A running application is the start of verification.</h3>
    <p>After deployment, inspect service health and diagnostics. Then check the behavior you intended: with a fresh, valid reading of 26°C, a fan starting off should now turn on and the display should report it.</p>
    <div class="story-check" role="group" aria-label="Illustrative acceptance check for a fan starting off at 26 degrees Celsius">
      <div><span>Test input</span><strong>26°C</strong><small>Fresh, valid climate reading</small></div>
      <div><span>Old threshold · 28°C</span><strong>Fan stays off</strong><small>Temperature below threshold</small></div>
      <div><span>New threshold · 26°C</span><strong>Fan turns on</strong><small>Display reports the new status</small></div>
    </div>
    <p class="story-scope">The starter produces 26°C at sample 4, while the fan is still off under the original 28°C setting. Keep the off threshold at 24°C. Runtime trial confirmation establishes liveness; the fan response and display result establish application behavior.</p>
  </div>
  <p class="story-deeper"><a href="site/updates-and-recovery/">Understand rejection, failed trials, and recovery →</a></p>
</section>

<div class="story-next">
  <span id="start-with-what-you-need"></span><span id="check-the-target-before-committing"></span>
  <h2>Take this model into your own application.</h2>
  <p>Evaluate <a href="site/is-micros-a-fit/">whether Micros fits your requirements</a>, then follow the architecture or try an existing application.</p>
  <div class="story-next-links"><a href="site/get-started/#create-your-project"><strong>Try composition locally <span aria-hidden="true">→</span></strong><span>Run the three-service climate starter without a device.</span></a><a href="site/service-boundaries/"><strong>Explore the service contract <span aria-hidden="true">→</span></strong><span>ABI, lifecycle, resource ownership, and platform support.</span></a><a href="site/get-started/#use-a-board"><strong>Choose your hardware <span aria-hidden="true">→</span></strong><span>Follow the setup path for your target.</span></a></div>
</div>

</div>

**Contracts behind the story:** [worker ownership and supervision](site/resources-and-failures.md), [bounded channels](site/messages-within-a-device.md), [declarations](site/declaration-authoring.md), and [updates and recovery](site/deploy-an-application.md).
{: .story-sources}

- [Interactive device shell](site/interactive-shell.md): inspect services, stream logs and invoke deployed commands.
