// The overview must never turn missing or inconsistent telemetry into measured usage.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = {window:{}};
vm.runInNewContext(fs.readFileSync('src/server/web/memory.js','utf8'),context);
const summary = context.window.microsMemory.summary;
const measured = summary({memory:{internal_total:4096,internal_free:1024,psram_total:8192,psram_free:6144}});
assert(measured.includes('Internal RAM: 3 KiB used, 1 KiB free, 4 KiB total'));
assert(measured.includes('PSRAM: 2 KiB used, 6 KiB free, 8 KiB total'));
for (const memory of [{},{internal_total:100,internal_free:101},{internal_total:100,internal_free:-1},{internal_total:100},{internal_total:0,internal_free:0}]) {
  const html = summary({memory});
  assert(!html.includes('role="img"'));
  assert(html.includes('Usage unavailable'));
  assert(!/NaN|Infinity/.test(html));
}
assert(summary({heap:2048}).includes('2 KiB free. Usage unavailable.'));
assert(!summary({heap:2048,memory:{internal_total:4096,internal_free:null}}).includes('role="img"'));
assert(summary({memory:{internal_total:100,internal_free:0}}).includes('100 B used, 0 B free'));
assert(summary({memory:{internal_total:100,internal_free:100}}).includes('0 B used, 100 B free'));
assert(!summary({memory:{psram_total:0,psram_free:0}}).includes('PSRAM'));
console.log('Memory summary: measured, missing, invalid, full, empty and disabled pools passed.');
