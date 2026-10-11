# Documentation visual concept

Three ECharts examples for the evaluator documentation. Source lives here;
generated browser and SVG assets live in `docs/`. The review page is
`docs/site/visual-storyboard.md` and is intentionally outside the navigation.

Run `npm ci --ignore-scripts` then `node build.mjs` in this directory to rebuild.
The package lock pins the renderer and bundler. Only custom-series,
grid, graphic, and SVG modules are bundled. The charts load on the review page
only. No CDN, telemetry, or device connection is used.

Static SVGs are generated from the same option functions as the browser charts;
they cover initial rendering, script failure, and printing. Essential semantics
are also available in figure descriptions and adjacent prose. The native controls
are the only interaction; all chart marks are intentionally noninteractive.

The story follows a proposed greenhouse application through the kernel,
communication, TOML composition, an update, and a behavior check. The first figure
distinguishes the service ABI from the platform interface; target adapters are
build alternatives. The second follows Climate sensor, Fan controller, and Status
display through `climate.reading` and `fan.status`. Both proposed channels use
`latest` retention. Arrows show message direction, not measured traffic volume.
Independent reader positions and bounded retention follow ADR 0006.
Explicit graphic endpoints keep arrows attached to the rectangular cards on
desktop and mobile. Update phases are ordinal, not time measurements. Selecting
failed startup hides the successful-update acceptance example, and describes
fallback to the prior graph and its 28°C setting.

The greenhouse application and schemas under `docs/assets/visual-storyboard/`
are labeled design artifacts, not deployable services. The linked composition
walkthrough uses the existing DHT deployment for real offline validation. The
27°C acceptance example on the main page is illustrative, not recorded telemetry.

Board-specific build measurements remain in
`docs/archive/documentation/architecture/flash-services.md`; they are not part of this introduction.

ECharts and ZRender are Apache-2.0 licensed, with bundled notices and applicable
third-party attributions included alongside the SVGs.
