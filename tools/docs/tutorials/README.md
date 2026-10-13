# Interactive documentation tutorials

The public SDK owns the lesson UI, prose and runnable examples. MkDocs serves
`/tutorials/`, `/tutorials/blink/` and `/tutorials/button/` under the same header
and navigation as Quickstart and Reference. No iframe or product-site dependency.

`toggle-lessons.js` defines steps; `ToggleTutorial.jsx` and `toggle-model.js`
implement the preview. Keep animation left and code right, compact filenames,
added-line notes, syntax colors and persistent Back/Continue controls.
Dummy pins require physical verification; simulation is not a board test.

From the SDK root, with Node.js 22:

```sh
npm ci --prefix tools/docs/tutorials
npm run build --prefix tools/docs/tutorials
build/python/bin/python -m mkdocs build --strict
npm test --prefix tools/docs/tutorials
```

Vite writes an ignored bundle to `build/docs-tutorials/`. The docs build copies
it and packages tracked `examples/tutorials/toggle/` files directly into its output.
Displayed code and the ZIP use the same bytes, with hashes and SDK revision in
`/tutorials/source.json`. Local uncommitted example edits are marked explicitly.
No duplicated source snapshot or separate synchronization step is maintained.
The tests check interaction behavior, annotations, displayed files and ZIP contents.
Run the example's compiled tests separately as described in its
[README](../../../examples/tutorials/toggle/README.md).

The product website links here; its legacy `/tutorials` URLs redirect to docs.
