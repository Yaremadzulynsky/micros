# Management console

User direction (September 14, 2026): the management console should share the micros website’s visual style and have a coherent operational workflow. Preserve existing monitoring and management features. The latest direction replaces browser deployment with a concise, board-specific micros CLI guide.

The visual reference is `src/styles.css` and the compact micros wordmark in the independent `micros-website` repository. This console owns its local assets and styles and must build and run without a website checkout. Preserve the shared design direction: Arial/Helvetica, white surfaces, neutral ink, restrained blue actions, pale blue OS/resource surfaces, and quiet borders. Keep semantic status colors. Resource charts use the website’s restrained blue/gray palette: one blue for services, muted blue-gray system usage, pale solid free memory, and hatching for reserved flash headroom or unknown regions. Preserve names, values and interactive details instead of assigning unrelated colors to services.

Keep the board context visible. Start with Your boards, then three primary tabs: Overview, Resources, and Investigate. Overview shows application state, measured RAM usage bars, and flash partition allocation. Keep flash reservations distinct from measured usage; unreported contents must not be labeled free. Resources opens RAM and flash directly, with hardware ownership and service reservations in disclosures. Service connections, timing, memory maps, hardware budgets, network diagnostics, and identity details open in context. Investigate contains Logs and Activity. Deployment stays on the Overview action, Application controls in the application footer, and Board settings in Device details; their contextual screens keep the three change options accessible. All capabilities, board selection, fleet search must remain accessible on mobile. Avoid reintroducing a permanent sidebar or displaying all technical details at once.

Preserve measured-versus-reserved memory semantics, unavailable telemetry states, offline/stale observations, confirmation flows, and existing authenticated APIs. Application compilation, validation and deployment happen in the CLI. Local design previews must use explicitly synthetic fixtures, not live-device mutations.

The console is served directly from this directory; it has no frontend build step. Use `tests/server/console_design_fixture.py` for a local synthetic preview and the server test suite for backend regression checks.

The fleet home uses a compact workbench welcome with the website's existing board artwork. Default board cards show every service name and a clear application/OS foundation; retain the Table alternative, search, filters, and distinct offline/empty/unobserved states. Keep decoration subordinate to operational context, and check the filter/view controls at 320px.

Overview includes a Sankey-style service flow: local publishers → named channels → local listeners. Use reported permission masks and channel keys, never inferred traffic. Each ribbon is one configured connection. Show a service in both roles when it publishes and listens; preserve stopped/offline and missing-data distinctions. Use the restrained blue-gray palette, smooth ribbons, direct names, hover and keyboard/click tracing. Keep the full chart horizontally scrollable on phones without shrinking labels. Channel diagnostics stay available through Inspect channels. The locally vendored D3 layout and license provenance are documented in THIRD_PARTY.md.

Remote routes appear as globe endpoints on the publishing or listening side, using the server's admitted routes for the exact observed application. Show the peer board name and route availability; never infer a remote publisher from an absent local permission. The network bridge keeps its service name and state, with a globe marking remote access. A globe means access beyond this board, not necessarily public Internet or an active reader. Preserve graph selection and zoom across availability updates.

The top bar has Boards and Connections. Connections opens the fleet graph as a dedicated full-page route (#view=Connections); keep the Boards home focused on cards, table and filters. Reuse the service graph renderer, layout, zoom and tracing, with publishing boards → named routes → listening boards. Deduplicate a route reported by both ends; never join boards just because their channel names match. Include disconnected boards and preserve the existing cards, table and filters. Selecting a board reveals its services and an Open board action. Synthetic preview connections must stay visibly labeled as examples.

## Direct console access — October 12, 2026

The console opens directly without operator-token sign-in, sessions or tickets.
This applies to existing and new servers. Keep CLI/operator API and device tokens,
same-origin mutation checks and the device-only listener boundary intact.
Remote console access is controlled by the network or external access gateway.
