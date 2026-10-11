// Regression checks for polling redraws; no browser or device connections.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2] || 'src/server/web/app.js', 'utf8');

function region(header, left=0, top=0, options={}) {
  return {
    id:options.id || '', className:options.className || 'table-wrap', scrollLeft:left, scrollTop:top,
    getAttribute(name) { return name==='aria-label' ? options.label || null : null; },
    querySelector(selector) { return selector==='thead' && header ? {textContent:header} : null; }
  };
}
function fixture() {
  const elements = new Map(), page = {scrollX:0, scrollY:0, addEventListener() {}}, intervals=[];
  let regions=[], renderCount=0, focusedInput=false, nextRegions=[];
  const element = selector => {
    if (!elements.has(selector)) elements.set(selector, {
      id:selector.slice(1), hidden:false, innerHTML:'', textContent:'',
      setAttribute(name,value) { this[name]=value; },
      addEventListener() {}, focus() {}, contains:()=>focusedInput,
      querySelector:()=>null, querySelectorAll:()=>selector==='#content' ? regions : []
    });
    return elements.get(selector);
  };
  page.scrollTo = (x,y) => {
    page.scrollX = typeof x==='object' ? x.left : x;
    page.scrollY = typeof x==='object' ? x.top : y;
  };
  const document = {querySelector:element, querySelectorAll:()=>[], addEventListener() {}, activeElement:{matches:()=>focusedInput}};
  const context = vm.createContext({window:page, document, TextDecoder, URLSearchParams,
    location:{hash:'#board=0123456789ab&view=Channels',pathname:'/console/'},
    history:{pushState() {},replaceState() {}}, setInterval:(fn,ms)=>intervals.push({fn,ms}),
    // Keep automatic startup pending; each test drives a separate real refresh below.
    fetch:()=>new Promise(()=>{}), renderHook() {
      renderCount++;
      regions=nextRegions;
      page.scrollX=0;page.scrollY=0; // New containers + a document-height clamp during mounting.
    }
  });
  vm.runInContext(source,context);
  vm.runInContext('state.refreshing=false;state.signedIn=true;render=renderHook;',context);
  const device={device_id:'0123456789ab',name:'Preview',online:true,status:{channels:[{published:13821}]}};
  context.api=async()=>({devices:[device]});
  return {page,context,device,intervals,element,
    setRegions(before,after) { regions=before;nextRegions=after; },
    focusInput() { focusedInput=true; },
    renderCount:()=>renderCount,
    refresh:()=>vm.runInContext('refresh()',context),
    navigate:()=>vm.runInContext('enterSection()',context)
  };
}

(async()=>{
  {
    const f=fixture(), next=[region('Channel Published'),region('Service State')];
    f.setRegions([region('Channel Published',650),region('Service State',120,35)],next);
    f.page.scrollX=12;f.page.scrollY=840;
    await f.refresh();
    assert.equal(next[0].scrollLeft,650,'Polling must retain the channel column being read');
    assert.equal(next[1].scrollTop,35,'Polling must retain nested vertical scroll');
    assert.equal(next[1].scrollLeft,120);
    assert.deepEqual([f.page.scrollX,f.page.scrollY],[12,840],'Chart mounting must not move the page');
    assert.equal(f.renderCount(),1,'The updated data must still render');
    assert.equal(vm.runInContext('state.devices[0].status.channels[0].published',f.context),13821);
  }
  {
    const f=fixture(), table=region('Channel Published',50), next=region('Channel Published');
    let finish;
    f.context.api=()=>new Promise(resolve=>{finish=resolve;});
    f.setRegions([table],[next]);f.page.scrollY=100;
    const pending=f.refresh();
    table.scrollLeft=480;f.page.scrollY=975; // User scrolls while the request is in flight.
    finish({devices:[f.device]});await pending;
    assert.equal(next.scrollLeft,480,'Use the latest position, not the request-start position');
    assert.equal(f.page.scrollY,975);
  }
  {
    const f=fixture(), next=[region('New table'),region('B'),region('A'),region('A'),region(null,0,0,{className:'graph-viewport',label:'Service flow'})];
    f.setRegions([region('A',60),region('B',90),region('A',180),region(null,240,80,{className:'graph-viewport',label:'Service flow'})],next);
    await f.refresh();
    assert.deepEqual(next.map(r=>r.scrollLeft),[0,90,60,180,240],'New/reordered tables must not steal another table’s position');
    assert.equal(next[4].scrollTop,80);
  }
  {
    const f=fixture();f.setRegions([],[]);f.page.scrollY=700;f.navigate();
    assert.equal(f.page.scrollY,0,'Intentional navigation must still start at the top');
  }
  {
    const f=fixture();
    vm.runInContext("chooseWorkspace('Connections')",f.context);
    assert.equal(vm.runInContext('route()',f.context),'#view=Connections');
    assert.equal(f.element('#connections-nav')['aria-current'],'page');
    vm.runInContext("location.hash='#view=Connections';readRoute()",f.context);
    assert.equal(vm.runInContext('state.tab',f.context),'Connections','Connections survives a reload or history navigation');
    vm.runInContext("chooseBoard('0123456789ab')",f.context);
    assert.equal(vm.runInContext('route()',f.context),'#board=0123456789ab&view=Overview');
    vm.runInContext("chooseWorkspace('Overview')",f.context);
    assert.equal(vm.runInContext('route()',f.context),'');
    assert.equal(f.element('#fleet-nav')['aria-current'],'page');
    vm.runInContext("state.busy=true;chooseWorkspace('Connections')",f.context);
    assert.equal(vm.runInContext('state.tab',f.context),'Overview','Navigation still respects an active board operation');
  }
  {
    const f=fixture(), table=region('Channel Published',320);f.setRegions([table],[region('Channel Published')]);
    f.focusInput();f.page.scrollY=510;await f.refresh();
    assert.equal(f.renderCount(),0,'Polling must still protect active input');
    assert.equal(table.scrollLeft,320);assert.equal(f.page.scrollY,510);
  }
  console.log('Polling scroll: page/table/graph positions, delayed responses, reordered tables, navigation and input protection passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
