// Measured RAM pools, unknown/private allocations, disabled PSRAM, and hover accessibility.
const {chromium}=require('playwright');
const fs=require('fs'),http=require('http'),assert=require('assert');
(async()=>{
 const status={memory:{internal_total:280000,internal_free:50000,internal_min:40000,internal_largest:32000,psram_total:0,psram_free:0},services:[{name:'button <test>',state:'Running',arena_reserved:64,stack_reserved:4096,stack_free_bytes:3072}]};
 status.heap_accounting={ipc_storage:8448,ipc_payload_capacity:8192,ipc_assigned:128,runtime_metadata:6000,supervisor_stack:4096};
 status.channels=[{key:1,name:'messages',depth:2,payload_bytes:64,retained_bytes:8,backlog:0}];
 const server=http.createServer((req,res)=>{
  res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'");
  if(req.url==='/fixture.js'){res.setHeader('Content-Type','text/javascript');return res.end(`document.querySelector('main').innerHTML=microsMemory.render(${JSON.stringify(status)});microsFlash.mount();`);}
  if(req.url==='/'){res.setHeader('Content-Type','text/html');return res.end('<meta charset="utf-8"><link rel="stylesheet" href="/style.css"><script src="/flash.js" defer></script><script src="/memory.js" defer></script><script src="/fixture.js" defer></script><main></main>');}
  if(!['/flash.js','/memory.js','/style.css'].includes(req.url)){res.statusCode=404;return res.end();}
  res.setHeader('Content-Type',req.url.endsWith('.js')?'text/javascript':'text/css');res.end(fs.readFileSync('src/server/web'+req.url));
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try{
  const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  page.on('console',m=>{if(m.type()==='error'&&m.text().includes('Content Security Policy'))errors.push(m.text());});
  for(const width of [1200,736,360]){
   await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:'+server.address().port);
   assert.equal(await page.locator('.ram-panel table').count(),0);
   const trigger=page.getByRole('button',{name:/button <test>, .* reserved/}),popup=page.locator('#ram-internal-service-0');
   assert.equal(await popup.isVisible(),false);await trigger.hover();assert.equal(await popup.isVisible(),true);
   const text=await popup.innerText();assert(text.includes('button <test>'));assert(text.includes('Current arena usage'));assert(text.includes('Not measured'));assert(text.includes('1 KiB / 4 KiB'));assert(text.includes('Peak since start'));
   const bounds=await popup.boundingBox();assert(bounds.x>=0&&bounds.x+bounds.width<=width);
   await popup.hover();assert.equal(await popup.isVisible(),true);
   await page.keyboard.press('Escape');assert.equal(await popup.isVisible(),false);
   await trigger.focus();assert.equal(await popup.isVisible(),true);
   await page.getByRole('button',{name:/Communication buffers, /}).hover();
   const ipc=await page.locator('#ram-internal-communication').innerText();assert(ipc.includes('8 B data / 128 B reserved'));assert(ipc.includes('8 KiB'));assert(ipc.includes('already-read buffers still reserve RAM'));
   await page.getByRole('button',{name:/Runtime, /}).hover();assert((await page.locator('#ram-internal-runtime').innerText()).includes('counted separately'));
   const sum=await page.locator('.ram-map').first().locator(':scope > [data-flash-weight]').evaluateAll(es=>es.reduce((n,e)=>n+Number(e.dataset.flashWeight),0));assert.equal(sum,280000);
   await page.getByRole('button',{name:'PSRAM, Not enabled',exact:true}).focus();assert.equal(await page.locator('#ram-psram-unavailable').isVisible(),true);
  }
  for(const memory of [{},{internal_total:100,internal_free:101},{internal_total:100,internal_free:0},{internal_total:100,internal_free:100},{psram_total:1024,psram_free:512}]){
   const result=await page.evaluate(memory=>{document.querySelector('main').innerHTML=microsMemory.render({memory});microsFlash.mount();return document.querySelector('main').innerHTML;},memory);
   assert(!result.includes('NaN'));assert(!result.includes('Infinity'));
   if(memory.internal_free===101)assert(result.includes('Usage measurements are unavailable'));
   if(memory.internal_free===0)assert(result.includes('Other heap usage, 100 B used'));
   if(memory.internal_free===100)assert(result.includes('Free, 100 B free'));
   if(memory.psram_total)assert(result.includes('Per-service PSRAM usage is unavailable'));
  }
  await page.evaluate(status=>{status.memory.psram_total=2097152;status.memory.psram_free=2097072;status.services[0].arena_pool='PSRAM';document.querySelector('main').innerHTML=microsMemory.render(status);microsFlash.mount();},status);
  assert.equal(await page.locator('[aria-label="Internal heap allocation breakdown"] > .flash-segment').first().getAttribute('data-flash-weight'),'4096');
  assert.equal(await page.locator('[aria-label="PSRAM allocation breakdown"] > .flash-segment').first().getAttribute('data-flash-weight'),'64');
  await page.mouse.move(0,0);
  await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'button <test>, 64 B in PSRAM',exact:true}).hover();
  assert((await page.locator('#psram-detail-0').innerText()).includes('Its stack remains in internal RAM'));
  assert.deepEqual(errors,[]);console.log('RAM hover, budgets vs usage, stack watermark, disabled/unknown pools, bounds and CSP checks passed.');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
