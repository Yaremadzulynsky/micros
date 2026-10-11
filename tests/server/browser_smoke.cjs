// Run from the repository root with Playwright available in NODE_PATH and Chrome installed.
// Read-only live-board checks; local private certificate bypass is isolated to this test browser.
const {chromium}=require('playwright');
const fs=require('fs');
(async()=>{
 fs.mkdirSync("build/usability-review",{recursive:true});
 const browser=await chromium.launch({headless:true,channel:"chrome"});
 const context=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width:1440,height:1000}});
 const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
 const origin=JSON.parse(fs.readFileSync('.micros/server/client.json')).url;
 const openAccess=(await context.request.get(origin+'/console/api/devices')).status()===200;
 await page.goto(origin+'/console/');
 if(!openAccess) {
 await page.locator('#token').fill(fs.readFileSync('.micros/server/admin.token','utf8').trim());
 await page.locator('#login-form button').click();
 }
 await page.locator('#shell').waitFor({state:'visible'});
 await page.screenshot({path:'build/usability-review/console-fleet.png',fullPage:true});
 console.log('Fleet:',await page.locator('#content').innerText());
 const roster=await page.evaluate(async()=> (await (await fetch('/console/api/devices')).json()).devices);
 const board=roster.find(device=>device.online && device.status?.services?.length) || roster.find(device=>device.online);
 if(!board)throw new Error('Browser integration check needs an online board.');
 await page.locator('.device-link[data-device="'+board.device_id+'"]').click();
 await page.screenshot({path:'build/usability-review/console-board.png',fullPage:true});
 const primary=page.getByRole('navigation',{name:'Board tasks'});
 await page.getByRole('button',{name:'View memory details',exact:true}).click();
 await page.locator('#heap-history summary').click();
 await page.locator('#chart-description').filter({hasText:'observations'}).waitFor();
 await primary.getByRole('button',{name:'Overview',exact:true}).click();
 await page.getByRole('button',{name:'Inspect services',exact:true}).click();
 await page.getByRole('button',{name:'Inspect service connections',exact:true}).click();
 await page.getByRole('button',{name:'Back to services',exact:true}).click();
 console.log('Services:',await page.locator('#content').innerText());
 await primary.getByRole('button',{name:'Investigate',exact:true}).click();
 await page.getByRole('button',{name:'Connection details',exact:true}).click();
 await page.getByRole('button',{name:'Back to investigation',exact:true}).click();await page.locator('[data-action="read-logs"]').click();
 await page.locator('#log-state').filter({hasText:'Read at'}).waitFor({timeout:30000});
 console.log('Logs read successfully');
 await primary.getByRole('button',{name:'Overview',exact:true}).click();
 await page.getByRole('button',{name:'Deploy from CLI',exact:true}).click();
 await page.getByRole('heading',{name:'One command to deploy.'}).waitFor();
 if(await page.locator('input[type=file]').count())throw new Error('CLI guide still shows upload controls');
 const deployURL=page.url();await page.reload();
 await page.getByRole('heading',{name:'One command to deploy.'}).waitFor();
 if(page.url()!==deployURL)throw new Error('Deployment guide lost board context on refresh');
 await page.goBack();await page.getByRole('heading',{name:board.name,exact:true}).waitFor();
 await primary.getByRole('button',{name:'Overview',exact:true}).click();
 await page.getByRole('button',{name:'Deploy from CLI',exact:true}).click();
 await page.screenshot({path:'build/usability-review/console-deploy.png',fullPage:true});
 await primary.getByRole('button',{name:'Overview',exact:true}).click();
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:'build/usability-review/console-mobile.png',fullPage:true});
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
 console.log(JSON.stringify({errors,mobileOverflow:overflow}));
 await browser.close();if(errors.length || overflow)process.exitCode=1;
})();
