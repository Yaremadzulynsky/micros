// Isolated browser fixture: no live board, account, or real passwords.
const {chromium}=require('playwright');
const fs=require('fs'),http=require('http'),assert=require('assert');
(async()=>{
 let online=true,compatible=true,posted=null;
 let networks=[{ssid:'Home Wi-Fi',fallback:false,secured:true}];
 const server=http.createServer(async(req,res)=>{
  res.setHeader('Content-Type','application/json');
  if(req.url==='/console/api/devices')return res.end(JSON.stringify({authentication_required:false,devices:[{device_id:'0123456789ab',name:'Feather',online,status:{network:{profiles_api:compatible?1:undefined},services:[],identity:{}}}]}));
  if(req.url.endsWith('/history'))return res.end('{"samples":[],"events":[]}');
  if(req.url.endsWith('/wifi')) {
   if(req.method==='POST') {
    let body='';for await(const chunk of req)body+=chunk;
    posted=JSON.parse(body);
    networks=posted.networks.flatMap((n,i)=>n?[{ssid:n.ssid,fallback:i===3,secured:n.password!==''}]:[]);
    return res.end('{"ok":true}');
   }
   return res.end(JSON.stringify({networks}));
  }
  const name=req.url==='/console/'?'index.html':req.url.split('/').at(-1);
  if(!['index.html','app.js','wifi.js','insights.js','flash.js','memory.js','style.css','micros-logo.png'].includes(name)){res.statusCode=404;return res.end('{}');}
  res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':name.endsWith('.png')?'image/png':'text/html');
  res.end(fs.readFileSync('src/server/web/'+name));
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try {
  const page=await browser.newPage({viewport:{width:1200,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  const open=async()=>{await page.goto('http://127.0.0.1:'+server.address().port+'/console/');await page.locator('.device-link').click();await page.locator('#device-details summary').click();await page.getByRole('button',{name:'Board settings',exact:true}).click();await page.locator('#network-settings summary').click();};
  await open();
  await page.getByText('Password saved on board. Leave blank to keep it.').waitFor();
  assert.equal(await page.locator('.wifi-row').count(),4);
  const names=page.locator('.wifi-ssid'),passwords=page.locator('.wifi-password');
  await names.nth(1).fill('Office');await passwords.nth(1).fill('test-secret-only');
  await names.nth(2).fill('Studio');await passwords.nth(2).fill('second-secret-only');
  await names.nth(3).fill('My iPhone');await passwords.nth(3).fill('hotspot-test-only');
  await page.getByRole('button',{name:'Save networks'}).click();
  await page.getByText('Saved on the board. Its current connection stays active;', {exact:false}).waitFor();
  assert.equal(posted.networks[0].password,null);
  assert.equal(posted.networks[3].password,'hotspot-test-only');
  assert.deepEqual(await passwords.evaluateAll(inputs=>inputs.map(i=>i.value)),['','','','']);
  await names.nth(1).fill('Home Wi-Fi');await page.getByRole('button',{name:'Save networks'}).click();
  await page.getByText('Use distinct network names of 1–32 UTF-8 bytes.').waitFor();
  await names.nth(1).fill('Office');
  fs.mkdirSync('build/wifi-settings',{recursive:true});await page.screenshot({path:'build/wifi-settings/settings-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
  await page.screenshot({path:'build/wifi-settings/settings-mobile.png',fullPage:true});
  await page.setViewportSize({width:1200,height:1000});
  networks.splice(3,0,{ssid:'Fourth legacy',fallback:false,secured:true});
  await open();await page.locator('.wifi-extra').waitFor();
  assert.equal(await page.locator('.wifi-extra input').getAttribute('required'),'');
  compatible=false;await open();await page.getByText('A compatible USB base update is required', {exact:false}).waitFor();
  assert.equal(await page.locator('.wifi-row').count(),0);
  online=false;await open();await page.getByText('Connect this board to edit its saved Wi-Fi networks.').waitFor();
  assert.deepEqual(errors,[]);
  console.log('PASS Settings: 3 primaries + fallback, saved-password preservation, clearing, duplicates, legacy list, mobile, old firmware and offline states');
 } finally {await browser.close();await new Promise(r=>server.close(r));}
})().catch(error=>{console.error(error);process.exitCode=1;});
