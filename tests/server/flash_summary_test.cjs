// Flash capacity and partition reservations must never be presented as measured free space.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = {window:{},document:{addEventListener(){}}};
vm.runInNewContext(fs.readFileSync('src/server/web/flash.js','utf8'),context);
const summary = context.window.microsFlash.summary;
const partition = (offset,size) => ({name:'application',offset,size});
const render = partitions => summary({flash:{total_bytes:4096,partitions}});
const measured = render([partition(1024,2048)]);
assert(measured.includes('2 KiB reserved, 2 KiB unmapped'));
assert(!measured.includes('free'));
assert(render([partition(0,4096)]).includes('4 KiB reserved'));
for (const partitions of [[],[partition(0,4097)],[partition(0,2048),partition(1024,2048)],[partition(-1,1024)]]) {
  const html = render(partitions);
  assert(html.includes('Partition layout unavailable'));
  assert(!html.includes('role="img"'));
  assert(!/NaN|Infinity|free/.test(html));
}
assert(summary({board:{flash_mb:4}}).includes('4 MiB total'));
assert(summary({}).includes('Capacity unavailable'));
assert(!summary({flash:{total_bytes:0,partitions:[partition(0,4096)]}}).includes('role="img"'));
console.log('Flash summary: partition allocation, gaps, invalid layouts and missing capacity passed.');
