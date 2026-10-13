# Service flow layout

The flow treatment is inspired by [ApexSankey](https://apexcharts.com/apexsankey/). It does not include ApexCharts or ApexSankey code.

`sankey.min.js` contains the D3 Sankey layout generator (d3-sankey 0.12.3) and tree-shaken d3-array helpers. The BSD-3-Clause notices are retained in `sankey.LICENSE.txt`. Package versions and npm integrity hashes are pinned in `tools/vendor/service-flow/package-lock.json`.

The bundle is served locally under the console CSP and needs no CDN or runtime frontend build. To reproduce from the repository root:

```sh
npm ci --prefix tools/vendor/service-flow --no-audit --no-fund
tools/vendor/service-flow/node_modules/.bin/esbuild tools/vendor/service-flow/entry.js --bundle --minify --format=iife --outfile=src/server/web/sankey.min.js
```

`service-graph.js` maps permissions to publisher/channel/listener roles. Each reported permission has equal weight; ribbons do not measure traffic. A service in both roles is intentionally represented at both ends, allowing feedback relationships without feeding cyclic input to Sankey. Dashed missing endpoints are visual placeholders and are excluded from permission tracing.
