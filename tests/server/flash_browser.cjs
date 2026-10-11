// Compact hover/focus view under the console's real CSP; no device writes.
const {chromium}=require('playwright');
const fs=require('fs'),http=require('http'),assert=require('assert');
(async()=>{
 const status={board:{flash_mb:8},flash:{total_bytes:8388608,partitions:[{name:'nvs',offset:36864,size:24576},{name:'services',offset:4325376,size:262144}],services:{slots:[{slot:1,name:'button <test>',offset:20480,reserved_bytes:16384,image_bytes:3628}]}}};
 const server=http.createServer((req,res)=>{
  res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'");
  if(req.url==='/fixture.js'){res.setHeader('Content-Type','text/javascript');return res.end(`document.querySelector('main').innerHTML=microsFlash.render(${JSON.stringify(status)});microsFlash.mount();`);}
  if(req.url==='/'){res.setHeader('Content-Type','text/html');return res.end('<meta charset="utf-8"><link rel="stylesheet" href="/style.css"><script src="/flash.js" defer></script><script src="/fixture.js" defer></script><main></main>');}
  if(!['/flash.js','/style.css'].includes(req.url)){res.statusCode=404;return res.end();}
  res.setHeader('Content-Type',req.url.endsWith('.js')?'text/javascript':'text/css');res.end(fs.readFileSync('src/server/web'+req.url));
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try{
  const page=await browser.newPage(),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('console',m=>{if(m.type()==='error'&&m.text().includes('Content Security Policy'))errors.push(m.text());});
  for(const width of [1200,736,360]){
   await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:'+server.address().port);
   const trigger=page.getByRole('button',{name:/button <test>, .* image, 16 KiB reserved/}),popup=page.locator('.flash-service-slot .flash-tooltip');
   assert.equal(await popup.isVisible(),false);
   await trigger.hover();assert.equal(await popup.isVisible(),true);
   assert((await popup.innerText()).includes('button <test>'));
   assert(!(await popup.innerText()).includes('Bank A'));
   assert.equal(await page.locator('.flash-service-slot').count(),1);
   assert((await popup.innerText()).includes('slot headroom'));
   assert(await popup.locator('.flash-image').evaluate(el=>el.getBoundingClientRect().width>0));
   const bounds=await popup.boundingBox();assert(bounds.x>=0&&bounds.x+bounds.width<=width);
   await popup.hover();assert.equal(await popup.isVisible(),true);
   await page.keyboard.press('Escape');assert.equal(await popup.isVisible(),false);
   await trigger.focus();assert.equal(await popup.isVisible(),true);
  }
  const missing=await page.evaluate(()=>microsFlash.render({board:{flash_mb:4}}));
  assert(missing.includes('Partition layout unavailable'));assert(!missing.includes('flash-map'));
  const invalid=await page.evaluate(()=>microsFlash.render({flash:{total_bytes:4096,partitions:[{name:'bad',offset:0,size:5000}]}}));
  assert(invalid.includes('Partition layout unavailable'));
  assert.deepEqual(errors,[]);console.log('Flash hover, focus, Escape, CSP, narrow layout, escaping and unknown-data checks passed.');
 } finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
