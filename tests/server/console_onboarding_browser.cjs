// Optional browser integration: synthetic servers only, no credentials or boards.
// NODE_PATH=PATH/TO/node_modules node tests/server/console_onboarding_browser.cjs
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const fs=require('node:fs');
const assert=require('node:assert/strict');
const output=process.env.MICROS_BROWSER_OUTPUT || 'build/console-onboarding';
fs.mkdirSync(output,{recursive:true});

async function fixture(empty) {
  const child=spawn('build/python/bin/python',['tests/server/console_design_fixture.py','--port','0','--reject-tickets',...(empty?['--empty']:[])]);
  try {
    const origin=await new Promise((resolve,reject)=>{
      let log='';
      const timer=setTimeout(()=>reject(new Error('Synthetic fixture did not start')),10000);
      child.on('error',error=>{clearTimeout(timer);reject(error);});
      child.on('exit',code=>{clearTimeout(timer);reject(new Error('Fixture exited: '+code));});
      child.stderr.on('data',chunk=>process.stderr.write(chunk));
      child.stdout.on('data',chunk=>{
        log+=chunk;
        const match=log.match(/http:\/\/127\.0\.0\.1:\d+/);
        if(match){clearTimeout(timer);resolve(match[0]);}
      });
    });
    return {child,origin};
  } catch(error) {child.kill();throw error;}
}

(async()=>{
  const browser=await chromium.launch({headless:true,channel:'chrome'});
  const fixtures=[],errors=[];
  try {
    const context=await browser.newContext({viewport:{width:1280,height:900}});
    const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
    const empty=await fixture(true);fixtures.push(empty);
    await page.goto(empty.origin+'/console/#ticket=expired-synthetic-ticket');
    await page.getByText('Sign-in failed. Rerun micros server console for a fresh link, or check your operator token.',{exact:true}).waitFor();
    assert.equal(page.url(),empty.origin+'/console/','Ticket must leave the address bar even on failure');
    await page.getByLabel('Operator token',{exact:true}).fill('synthetic-operator-token');
    await page.getByRole('button',{name:'Sign in',exact:true}).click();
    await page.getByRole('button',{name:'Enroll your first board',exact:true}).click();
    const dialog=page.getByRole('dialog',{name:'Enroll a board'});
    await dialog.getByRole('heading',{name:'Plug in. Run enroll.'}).waitFor();
    assert.equal(await dialog.getByLabel('Device name',{exact:true}).isVisible(),false);
    assert.equal(await dialog.locator('#enroll-server').textContent(),empty.origin);
    await page.screenshot({path:output+'/enrollment-desktop.png',fullPage:true});
    await page.setViewportSize({width:320,height:780});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    assert.equal(await dialog.evaluate(el=>el.scrollWidth>el.clientWidth),false);
    await page.screenshot({path:output+'/enrollment-mobile.png',fullPage:true});
    await dialog.getByText('Advanced: manual authorization',{exact:true}).click();
    await dialog.getByLabel('Device name',{exact:true}).fill('Synthetic starter');
    await dialog.getByLabel('Device ID (MAC, without colons)',{exact:true}).fill('abcdef012345');
    await dialog.getByRole('button',{name:'Create enrollment',exact:true}).click();
    await dialog.getByRole('heading',{name:'Enrollment ready'}).waitFor();
    await dialog.getByRole('button',{name:'Download certificate'}).waitFor();
    await dialog.getByRole('button',{name:'Done',exact:true}).click();
    await page.getByRole('button',{name:'Enroll your first board',exact:true}).click();
    await dialog.getByRole('heading',{name:'Plug in. Run enroll.'}).waitFor();
    assert.equal(await dialog.getByLabel('Device name',{exact:true}).isVisible(),false);
    await dialog.getByRole('button',{name:'Close',exact:true}).click();
    const populated=await fixture(false);fixtures.push(populated);
    await page.goto(populated.origin+'/console/');
    await page.getByRole('button',{name:'Open New board',exact:true}).click();
    await page.getByRole('button',{name:'Deploy your first application',exact:true}).click();
    await page.getByRole('heading',{name:'One command to deploy.'}).waitFor();
    assert.equal(await page.getByText('micros deploy -d 0123456789ad',{exact:true}).count(),1);
    assert.match(await page.locator('#content').innerText(),/Hello world/);
    const url=page.url();await page.reload();
    await page.getByRole('heading',{name:'One command to deploy.'}).waitFor();
    assert.equal(page.url(),url);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    assert.deepEqual(errors,[]);
    console.log('Passed: expired sign-in recovery, empty fleet, guided enrollment, manual fallback, completion reset, 320px layout, board-specific deployment and reload. Synthetic data only.');
  } finally {for(const {child} of fixtures)child.kill();await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
