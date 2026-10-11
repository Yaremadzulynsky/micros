'use strict';
const $ = selector => document.querySelector(selector);
const escapeHtml = value => String(value ?? '—').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
const bytes = value => Number.isFinite(value) ? (value / 1024).toFixed(1) + ' KiB' : '—';
const duration = value => !Number.isFinite(value) ? '—' : Math.floor(value / 3600) + 'h ' + Math.floor(value % 3600 / 60) + 'm';
const date = value => value ? new Date(value * 1000).toLocaleString() : 'Never';
const state = {devices:[], selected:null, tab:'Overview', signedIn:false, history:null, busy:false, cursor:0, boot:null, logs:'', decoder:new TextDecoder(), follow:false, logBusy:false, refreshing:false, filter:'all', query:'', fleetView:'cards'};
// A small task navigation; technical tools are reached in their context.
const tasks = [
  {label:'Overview', tab:'Overview', sections:['Overview','Services','Channels','Deploy','Controls','Settings']},
  {label:'Resources', tab:'Resources', sections:['Resources']},
  {label:'Investigate', tab:'Logs', sections:['Logs','Activity','Network']}
];
const sectionCopy = {
  Overview: ['Overview', ''],
  Services: ['Service details', 'Inspect the state and behavior of the programs on this board.'],
  Channels: ['Service connections', 'See how your services exchange messages.'],
  Logs: ['Investigate', 'Read diagnostic output to understand what happened.'],
  Resources: ['Resources', 'See where your memory goes.'],
  Network: ['Connection details', 'Inspect the board’s connection to your network.'],
  Activity: ['Investigate', 'Review observed changes and console operations.'],
  Deploy: ['Deploy from CLI', 'Deploy from your terminal. Follow your application here.'],
  Controls: ['Application controls', 'Pause, recover, or restart this board.'],
  Settings: ['Board settings', 'Manage the board’s name, networks, and access.']
};
const investigationTabs=[['Logs','Logs'],['Activity','Activity']];
const changeTabs=[['Deploy','Deploy from CLI'],['Controls','Application controls'],['Settings','Board settings']];
function route() { return state.selected?'#'+new URLSearchParams({board:state.selected,view:state.tab}):state.tab==='Connections'?'#view=Connections':''; }
function saveRoute() { if(location.hash!==route())history.pushState(null,'',location.pathname+route()); }
function readRoute() {
  const params=new URLSearchParams(location.hash.slice(1)), id=params.get('board');
  const selected=/^[a-f0-9]{12}$/.test(id||'')?id:null;
  if(selected!==state.selected){state.logs='';state.cursor=0;state.boot=null;state.decoder=new TextDecoder();}
  state.selected=selected;state.tab=!selected&&params.get('view')==='Connections'?'Connections':Object.hasOwn(sectionCopy,params.get('view'))?params.get('view'):'Overview';state.follow=false;
}
window.addEventListener('hashchange',()=>{
  if(location.hash==='#content')return;
  if(state.busy){history.replaceState(null,'',location.pathname+route());notice('Wait for the current board operation to finish.');return;}
  readRoute();enterSection();
});
function deploymentGuide(device) {
  // Prefer an unambiguous, shell-safe display name; unusual/duplicate names use the stable ID.
  const target=/^[a-zA-Z0-9][a-zA-Z0-9._-]*$/.test(device.name)&&state.devices.filter(d=>d.name===device.name).length===1?device.name:device.device_id;
  const command='micros deploy -d '+target;
  const code=(value,label)=>`<div class="cli-command"><code>${escapeHtml(value)}</code><button data-action="copy-command" data-command="${escapeHtml(value)}" aria-label="${label}">Copy</button></div>`;
  return `<section class="panel cli-guide"><p class="eyebrow">From your project to ${escapeHtml(device.name)}</p><h2>One command to deploy.</h2><p>Open your micros project in a terminal and run:</p>${code(command,'Copy deployment command')}<p class="cli-explainer">micros builds your application, checks compatibility and memory, then deploys it to this board. The terminal reports progress and confirms when services are running.</p><div class="cli-follow"><div><h3>See it running here</h3><p>Return to the board to check your services, memory and logs.</p></div><button data-tab="Overview">View board</button></div>${disclosure('Preview changes before deploying',`<p>Build and validate the update without changing the board.</p>${code(command+' --dry-run','Copy preview command')}`)}${disclosure('First time using the CLI?',`<p>Run from the micros repository with the CLI configured for this management server and your board’s application selected. If micros is not on your PATH, use <code>./micros</code>.</p><p><a href="https://yaremadzulynsky.github.io/micros/">Open the micros setup guide</a></p>`)}<p class="caption">Application services pause briefly during transfer. Resident management stays available.${device.online?'':' Reconnect this board before deploying.'}</p></section>`;
}
function attention(device) { return device.online && (device.status?.activation?.pending || (device.status?.services||[]).some(s=>!['Running','Stopped'].includes(s.state)||(Number.isFinite(s.result)&&s.result!==0))); }
function enterSection() { saveRoute(); $('#notice').hidden=true; renderNav(); render(); $('#content').focus({preventScroll:true}); window.scrollTo(0,0); }
function chooseBoard(id) {
  if(state.busy){notice('Wait for the current board operation to finish.');$('#board-switcher').value=state.selected;return;}
  state.selected=id;state.tab='Overview';state.logs='';state.cursor=0;state.boot=null;state.decoder=new TextDecoder();state.follow=false;
  enterSection();
}
function appStatus(status) { if(!status.activation)return 'Unavailable'; return status.activation?.pending ? 'Awaiting confirmation' : status.activation?.good<2 ? 'Confirmed release' : 'No confirmed release'; }
function sectionTabs(items,label) { return `<nav class="context-tabs" aria-label="${label}">${items.map(([tab,title])=>`<button data-tab="${tab}" aria-current="${state.tab===tab?'page':'false'}">${title}</button>`).join('')}</nav>`; }
function disclosure(title,body,id='') { return `<details class="detail-disclosure"${id?` id="${id}"`:''}><summary>${title}</summary><div class="disclosure-body">${body}</div></details>`; }
function serviceRows(services) { return services.map((s,i)=>`<div class="runtime-service"><div><strong>${escapeHtml(s.name || 'Unnamed service '+(i+1))}</strong><span>${s.version?'v'+escapeHtml(s.version):'Runtime index '+i}</span></div><span class="pill ${s.state==='Running'?'online':s.state==='Stopped'?'offline':'warning'}">${escapeHtml(s.state||'Unknown')}</span></div>`).join(''); }
function boardFacts(device) {
  const status=device.status||{};
  return `<dl class="facts"><dt>Device ID</dt><dd class="mono">${device.device_id}</dd><dt>Uptime</dt><dd>${duration(status.uptime_us/1e6)}</dd><dt>Platform</dt><dd>${escapeHtml(status.platform)}</dd><dt>Application</dt><dd>${appStatus(status)}</dd><dt>ABI</dt><dd>${escapeHtml(status.identity?.abi_major)}.${escapeHtml(status.identity?.abi_revision)}</dd><dt>Service slots</dt><dd>${escapeHtml(status.identity?.slots)}</dd><dt>Code per slot</dt><dd>${bytes(status.identity?.code_bytes)}</dd><dt>Data per slot</dt><dd>${bytes(status.identity?.data_bytes)}</dd><dt>Reset reason (raw)</dt><dd>${escapeHtml(status.reset_reason)}</dd><dt>Wi-Fi signal</dt><dd>${status.network?.rssi_dbm==null?'Unavailable':escapeHtml(status.network.rssi_dbm)+' dBm'}</dd></dl><div class="disclosure-actions"><button class="text-button" data-tab="Settings">Board settings</button><button class="text-button" data-tab="Network">Connection details</button><button class="text-button" data-action="export">Export status JSON</button><button class="text-button" data-action="fresh" ${!device.online||state.busy?'disabled':''}>Refresh status</button></div>`;
}
function applicationNotice(device) {
  const status=device.status||{}, services=status.services||[];
  if(!device.online)return '';
  if(status.activation?.pending)return '<div class="board-alert"><div><strong>Waiting for application confirmation</strong><p>Check the latest service state before starting another update.</p></div><button data-tab="Services">Inspect services</button></div>';
  if(services.some(s=>!['Running','Stopped'].includes(s.state)||(Number.isFinite(s.result)&&s.result!==0)))return '<div class="board-alert"><div><strong>Check the application</strong><p>A service reported an error or an unexpected state. Inspect its result and recent logs.</p></div><button data-tab="Logs">Investigate</button></div>';
  if(services.length&&services.every(s=>s.state==='Stopped'))return '<div class="board-alert"><div><strong>The application is stopped</strong><p>Device management is still available.</p></div><button data-tab="Controls">Application controls</button></div>';
  return '';
}
function overview(device) {
  const status=device.status||{}, services=status.services||[];
  return `${applicationNotice(device)}<div class="board-summary"><section class="panel application-panel"><div class="panel-head"><h2>Application</h2><span class="caption">${services.length?services.filter(s=>s.state==='Running').length+' of '+services.length+(device.online?' running':' last running'):'No services loaded'}</span></div><div class="runtime-services">${services.length?serviceRows(services)+(services.some(s=>!s.name)?'<p class="caption service-label-note">Service names are missing from this server’s release records. Open service details for more information.</p>':''):'<div class="empty"><h3>Give this board a job.</h3><p>Deploy an application to start running services.</p><button class="primary" data-tab="Deploy">Deploy your first application</button></div>'}</div><div class="os-foundation"><strong>micros OS</strong><span>${device.online?'Device management available':'Last observed configuration'}</span></div><div class="panel-footer"><button data-tab="Services" class="text-button">Inspect services</button><button data-tab="Controls" class="text-button">Application controls</button></div></section><section class="panel resource-summary"><h2>Resources</h2>${window.microsMemory.summary(status)}${window.microsFlash.summary(status)}<button data-tab="Resources" class="text-button">View memory details</button></section></div>${window.microsGraph.render(status,device.online,device.device_id)}${disclosure('Device details',boardFacts(device),'device-details')}`;
}
function controls(device) {
  const disabled=!device.online||state.busy?'disabled':'';
  return `<section class="panel control-list"><div class="control-row"><div><h2>Pause application</h2><p>Stop application services while keeping management available.</p></div><button data-action="pause" ${disabled}>Pause application</button></div><div class="control-row"><div><h2>Recover confirmed application</h2><p>Restore and start the last confirmed application release.</p></div><button data-action="recover" ${disabled}>Recover confirmed application</button></div><div class="control-row"><div><h2>Reboot board</h2><p>Restart the entire board. Management reconnects after the reboot.</p></div><button data-action="reboot" ${disabled}>Reboot board</button></div><p class="caption">Confirmation checks runtime liveness, not physical wiring or application correctness.</p></section>`;
}
const devicePath = id => '/api/devices/' + id;
const current = () => state.devices.find(device => device.device_id === state.selected);
async function api(path, payload, options={}) {
  const response = await fetch('/console' + path, {credentials:'same-origin', cache:'no-store', signal:options.signal, ...(payload === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)})});
  if(response.status===401){showLogin();throw new Error('Your session has ended. Sign in to continue.');}
  if(response.redirected || !(response.headers.get('content-type')||'').includes('application/json'))throw new Error('The connection or sign-in session needs to be renewed.');
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401) showLogin();
    throw new Error(data.error || 'Request failed (' + response.status + ')');
  }
  return data;
}
function notice(message, error=false) {
  $('#notice').hidden = false; $('#notice').textContent = message; $('#notice').className = error ? 'banner' : 'success';
}
function showLogin() { document.querySelectorAll('.wifi-password').forEach(input=>input.value=''); state.signedIn=false; state.follow=false; $('#shell').hidden=true; $('#login').hidden=false; }
function showShell() { state.signedIn=true; $('#shell').hidden=false; $('#login').hidden=true; }
function pill(device) { return `<span class="pill ${device.online?'online':'offline'}"><span class="dot"></span>${device.online?'Online':'Offline'}</span>`; }
function metric(label,value) { return `<div class="metric"><span class="metric-label">${label}</span><strong>${escapeHtml(value)}</strong></div>`; }
async function refresh() {
  if (state.refreshing) return;
  state.refreshing=true;
  try {
    const data=await api('/api/devices'); state.devices=data.devices; $('#logout').hidden=data.authentication_required===false; showShell();
    $('#connection-error').hidden=true; $('#server-label').textContent='Server connected'; $('#server-dot').className='dot online';
    $('#updated').textContent='Updated '+new Date().toLocaleTimeString();
    renderNav();
    if ((!state.selected && !$('#content').querySelector('.is-panning') && !($('#content').contains(document.activeElement) && document.activeElement.matches('input,textarea,select,summary,.flash-region,.graph-node,.graph-viewport,[data-graph-action]'))) || (['Overview','Resources','Services','Channels','Network'].includes(state.tab) && !($('#content').contains(document.activeElement) && document.activeElement.matches('input,textarea,select,summary,.flash-region,.graph-node,.graph-viewport,[data-graph-action]')) && !$('#content').querySelector('details[open], .flash-segment:hover, .is-panning'))) renderObservation();
  } catch(error) {
    if (state.signedIn) { $('#connection-error').hidden=false; $('#connection-error').innerHTML='<div><strong>Connection interrupted</strong><p>Displayed observations may be stale. '+escapeHtml(error.message)+'</p></div><div class="actions"><button data-action="retry-connection">Retry connection</button><a href="'+escapeHtml(location.pathname+location.hash)+'">Reopen console / sign in</a></div>'; $('#server-label').textContent='Disconnected'; $('#server-dot').className='dot offline'; }
  } finally { state.refreshing=false; }
}
function renderNav() {
  const device=current(),connections=!state.selected&&state.tab==='Connections';
  $('#fleet-nav').setAttribute('aria-current',connections?'false':'page');
  $('#connections-nav').setAttribute('aria-current',connections?'page':'false');
  $('#board-location').hidden=!device;
  const options=state.devices.map(d=>`<option value="${d.device_id}">${escapeHtml(d.name)}${d.online?'':' · Offline'}</option>`).join('');
  if($('#board-switcher').innerHTML!==options)$('#board-switcher').innerHTML=options;
  $('#board-switcher').value=state.selected||'';
  $('#section-nav').hidden=!device;
  const navHtml=device?tasks.map(task=>`<button data-tab="${task.tab}" class="task-nav" aria-current="${task.sections.includes(state.tab)?'page':'false'}">${task.label}</button>`).join(''):'';
  if($('#section-nav').innerHTML!==navHtml)$('#section-nav').innerHTML=navHtml;
}
function preserveContentFocus() {
  const element=document.activeElement;
  if(!$('#content').contains(element))return ()=>{};
  const attribute=['id','data-action','data-tab','data-filter','data-fleet-view','data-device'].find(key=>element.hasAttribute(key));
  if(!attribute)return ()=>{};
  const value=element.getAttribute(attribute);
  return ()=>$('#content').querySelector(`[${attribute}="${CSS.escape(value)}"]`)?.focus({preventScroll:true});
}
function renderObservation() {
  // Capture at render time, after the fetch: the user may have scrolled while waiting.
  const left=window.scrollX, top=window.scrollY, positions=new Map();
  const regions=()=>$('#content').querySelectorAll('.table-wrap, .graph-viewport, .log');
  const key=element=>element.id || element.getAttribute('aria-label') || element.querySelector('thead')?.textContent || element.className;
  for(const element of regions()) {
    const name=key(element);
    if(!positions.has(name))positions.set(name,[]);
    positions.get(name).push({left:element.scrollLeft,top:element.scrollTop});
  }
  render();
  // Replacing content creates new scroll containers. Match tables by their headers,
  // not by their position among other panels, and retain repeated tables separately.
  for(const element of regions()) {
    const position=positions.get(key(element))?.shift();
    if(position){element.scrollLeft=position.left;element.scrollTop=position.top;}
  }
  // Mounting charts can temporarily shorten the document and clamp the page scroll.
  window.scrollTo({left,top,behavior:'instant'});
}
function render() {
  const restoreFocus=preserveContentFocus();
  window.microsGraph.stop();
  const device=current();
  if (!device) { if(state.tab==='Connections')renderConnections();else renderFleet(); return; }
  const status=device.status || {}, services=status.services || [];
  const [heading,description]=sectionCopy[state.tab];
  const parents={Services:['Overview','Back to overview'],Channels:['Services','Back to services'],Network:['Logs','Back to investigation']};
  const parent=parents[state.tab];
  const subnav=investigationTabs.some(([key])=>key===state.tab)?sectionTabs(investigationTabs,'Investigation tools'):changeTabs.some(([key])=>key===state.tab)?sectionTabs(changeTabs,'Change options'):'';
  const title=`${parent?`<button class="back-link text-button" data-tab="${parent[0]}">${parent[1]}</button>`:''}<div class="title-row"><div><h1>${state.tab==='Overview'?escapeHtml(device.name):heading}</h1>${state.tab==='Overview'?`<div class="board-health">${pill(device)}<span>${escapeHtml(status.board?.profile||status.platform||'Board')}</span><span>Last contact ${date(device.last_seen)}</span></div>`:`<p class="subtitle">${description}</p>`}</div>${state.tab==='Overview'&&services.length?'<button data-tab="Deploy">Deploy from CLI</button>':''}</div>${!device.online?'<div class="banner">This board is offline. These are its last reported observations. Reconnect it to read live data or change its application.</div>':''}${subnav}`;
  let body='';
  if (state.tab==='Overview') {
    body=overview(device);
  } else if (state.tab==='Controls') {
    body=controls(device);
  } else if (window.microsInsights[state.tab]) {
    body=window.microsInsights[state.tab](status);
    if(state.tab==='Services')body+='<div class="context-links"><button class="text-button" data-tab="Channels">Inspect service connections</button><button class="text-button" data-tab="Resources">Inspect resource budgets</button></div>';
    if(state.tab==='Resources')body+=disclosure('Heap history · last 24 hours','<canvas class="chart" id="heap-chart" aria-label="Free heap history"></canvas><p class="caption" id="chart-description">Loading observations…</p>','heap-history');

  } else if (state.tab==='Logs') {
    body=`<section class="panel"><div class="panel-head"><div><h2>Diagnostic logs</h2><span class="caption">Device ring buffer · gaps and reboots are marked</span></div><div class="actions"><button data-action="read-logs" ${!device.online?'disabled':''}>Read logs</button><button data-action="follow" ${!device.online?'disabled':''}>${state.follow?'Stop following':'Follow logs'}</button></div></div><pre id="log-output" class="log" tabindex="0"></pre><p id="log-state" class="caption"></p></section>`;
  } else if (state.tab==='Deploy') {
    body=deploymentGuide(device);
  } else if (state.tab==='Activity') {
    body='<section class="panel"><h2>Activity</h2><p class="caption">Console operations, observed reboots, connectivity changes and service lifecycle transitions. Short events between check-ins may not be captured.</p><div id="events">Loading activity…</div></section>';
  } else {
    body=`<section class="panel"><h2>Board name</h2><form id="rename-form"><label>Display name<input name="name" value="${escapeHtml(device.name)}" required maxlength="80"></label><button>Save name</button></form></section>${disclosure('Wi-Fi networks','<div id="wifi-settings"></div>','network-settings')}${disclosure('Base identity &amp; management access',`<h3>Exact base identity</h3><p class="mono">${escapeHtml(status.identity?.base_sha256)}</p><div class="actions"><button data-action="export">Export status JSON</button><button data-action="revoke" class="danger">Revoke enrollment</button></div><p>Revoking disconnects this identity from management. Provision new credentials to reconnect it.</p>`,'access-settings')}`;

  }
  const diagnosticLinks=investigationTabs.some(([key])=>key===state.tab)?'<div class="context-links"><span>Checking the device itself?</span><button data-tab="Network" class="text-button">Connection details</button><button data-tab="Resources" class="text-button">Memory &amp; hardware</button></div>':'';
  $('#content').innerHTML=title+body+diagnosticLinks;
  window.microsFlash.mount();
  window.microsGraph.mount();
  if ($('#network-settings')) $('#network-settings').addEventListener('toggle',event=>{
    const details=event.currentTarget, root=details.querySelector('#wifi-settings');
    if(details.isConnected && details.open && !root.dataset.loaded){root.dataset.loaded='true';window.microsWifi.mount(root,device,api,busy=>{state.busy=busy;});}
  });
  if ($('#heap-history')) $('#heap-history').addEventListener('toggle',event=>{if(event.currentTarget.isConnected && event.currentTarget.open)loadHistory(device.device_id);});
  if ($('#log-output')) $('#log-output').textContent=state.logs || 'No logs fetched yet.';
  if (state.tab==='Activity' || state.tab==='Network') loadHistory(device.device_id);
  restoreFocus();
}
function lastContact(value) {
  if(!Number.isFinite(value)||value<=0)return 'Not connected yet';
  const minutes=Math.max(0,Math.floor((Date.now()/1000-value)/60));
  const label=minutes<1?'Just now':minutes<60?minutes+' min ago':minutes<1440?Math.floor(minutes/60)+' hr ago':new Date(value*1000).toLocaleDateString();
  return `<time datetime="${new Date(value*1000).toISOString()}" title="${escapeHtml(date(value))}">${label}</time>`;
}
function fleetApplication(device) {
  const services=device.status?.services;
  if(!Array.isArray(services))return 'Waiting for first check-in';
  if(!services.length)return 'No application yet';
  return `${services.filter(s=>s.state==='Running').length} / ${services.length} ${device.online?'running':'last running'}`;
}
function boardCard(device) {
  const status=device.status||{}, services=status.services, loaded=Array.isArray(services), check=attention(device);
  return `<article class="workbench-card${device.online?'':' is-offline'}" aria-labelledby="board-title-${device.device_id}">
    <div class="workbench-card-head"><span class="board-platform">${escapeHtml(status.board?.profile||status.platform||'Awaiting first connection')}</span>${pill(device)}</div>
    <h2 id="board-title-${device.device_id}"><button class="device-link" data-device="${device.device_id}">${escapeHtml(device.name)}</button></h2>
    <p class="board-card-id mono">${device.device_id}</p>
    <div class="board-application"><div class="board-application-heading"><span>${device.online?'Application':'Last observed application'}</span><span class="${check?'warning-text':''}">${check?'Needs attention':loaded&&services.length?fleetApplication(device):''}</span></div>
      ${loaded&&services.length?`<ul class="board-service-list">${services.map((service,index)=>`<li><span class="service-dot ${device.online?(service.state==='Running'&&(!Number.isFinite(service.result)||service.result===0)?'is-running':service.state==='Stopped'?'':'is-warning'):''}" aria-hidden="true"></span><span>${escapeHtml(service.name||'Unnamed service '+(index+1))}</span><span class="service-state">${escapeHtml(service.state||'Unknown')}</span></li>`).join('')}</ul>`:`<div class="board-ready"><strong>${loaded?'Ready for your next idea.':'Waiting to hear from this board.'}</strong><p>${loaded?'Deploy a service to give this board a job.':'Its application will appear after it connects.'}</p></div>`}
    </div>
    <div class="board-os"><strong>micros OS</strong><span>${device.online?'Connected & ready':device.last_seen?'Last seen '+lastContact(device.last_seen):'Awaiting connection'}</span></div>
    <div class="board-card-foot"><div><span>Available heap${!device.online?' · last seen':''}</span><strong>${bytes(status.heap)}</strong></div><button id="open-board-${device.device_id}" class="text-button" data-device="${device.device_id}" aria-label="Open ${escapeHtml(device.name)}">Open board</button></div>
  </article>`;
}
function fleetTable(devices) {
  return `<div class="table-wrap fleet-table"><table aria-label="Your boards"><thead><tr><th>Board</th><th>Connection</th><th>Application</th><th>Available heap</th><th>Last contact</th></tr></thead><tbody>${devices.map(d=>`<tr><td><button class="device-link" data-device="${d.device_id}">${escapeHtml(d.name)}</button><small class="mono">${d.device_id}</small></td><td>${pill(d)}</td><td>${fleetApplication(d)}${attention(d)?'<small class="warning-text">Check application</small>':''}</td><td>${bytes(d.status?.heap)}</td><td>${date(d.last_seen)}</td></tr>`).join('')}</tbody></table></div>`;
}
function renderFleet() {
  const restoreFocus=preserveContentFocus();
  const query=state.query.trim().toLowerCase(), devices=state.devices.filter(d=>(d.name+d.device_id).toLowerCase().includes(query)).filter(d=>state.filter==='all'||(state.filter==='online'&&d.online)||(state.filter==='offline'&&!d.online)||(state.filter==='attention'&&attention(d)));
  const online=state.devices.filter(d=>d.online).length, running=state.devices.reduce((n,d)=>n+(d.online?(d.status?.services||[]).filter(s=>s.state==='Running').length:0),0);
  const summary=state.devices.length?`${state.devices.length} enrolled · ${online} online · ${state.devices.length-online} offline · ${running} services running`:'Start with one board. Keep building from there.';
  $('#content').innerHTML=`<section class="workbench-welcome" aria-label="Your workbench"><div><p class="eyebrow">The micros workbench</p><h1>Your boards.</h1><p class="workbench-intro">See what’s running. Check in on your hardware.<br>Keep bringing your ideas to life.</p><p class="workbench-summary">${summary}</p></div><img src="/console/workbench-board.png" alt="" width="360" height="166" class="workbench-art"></section>
    <div class="workbench-section-head"><h2>${state.devices.length?'On your workbench':'Connect your first board'}</h2><button data-action="enroll" class="primary">Enroll a board</button></div>
    <div class="fleet-tools"><label class="fleet-search"><span class="sr-only">Search boards</span><input id="fleet-search" type="search" placeholder="Search name or device ID" value="${escapeHtml(state.query)}"></label><div class="fleet-options"><label class="fleet-filter">Show <select id="fleet-filter">${[['all','All boards'],['online','Online'],['offline','Offline'],['attention','Need attention']].map(([key,label])=>`<option value="${key}"${state.filter===key?' selected':''}>${label}</option>`).join('')}</select></label><div class="fleet-view" role="group" aria-label="Board layout">${['cards','table'].map(view=>`<button data-fleet-view="${view}" aria-pressed="${state.fleetView===view}">${view==='cards'?'Cards':'Table'}</button>`).join('')}</div></div></div>
    ${devices.length?(state.fleetView==='table'?fleetTable(devices):`<div class="workbench-grid">${devices.map(boardCard).join('')}</div>`):`<div class="empty workbench-empty"><h2>${state.devices.length?'No matching boards.':'A small board. A place to start.'}</h2><p>${state.devices.length?'Try a different name or clear the filter.':'Enroll its identity, then provision it to connect to this server. Your services and their status will appear here.'}</p><button data-action="${state.devices.length?'clear-filters':'enroll'}">${state.devices.length?'Clear filters':'Enroll your first board'}</button></div>`}
    <div class="workbench-notes"><p>Build in your terminal. See it running here.</p><span>Open a board for services, logs and CLI deployment instructions.</span></div>`;
  restoreFocus();
}
function renderConnections() {
  const restoreFocus=preserveContentFocus();
  $('#content').innerHTML=`<div class="connections-page">${state.devices.length?window.microsGraph.renderFleet(state.devices,true):'<h1>Connections</h1><div class="empty"><h2>Your workbench starts with a board.</h2><p>Enroll a board to see its connections here.</p><button class="primary" data-action="enroll">Enroll a board</button></div>'}</div>`;
  window.microsGraph.mount();
  restoreFocus();
}
async function loadHistory(id) {
  try {
    const history=await api(devicePath(id)+'/history'); if(state.selected!==id)return;
    state.history=history;
    if($('#events')) $('#events').innerHTML=history.events.map(event=>`<div class="event"><strong>${escapeHtml(event.action)} · ${escapeHtml(event.outcome)}</strong><small>${date(event.time)}</small><p>${escapeHtml(event.detail)}</p></div>`).join('') || '<div class="empty">No console activity recorded yet.</div>';
    if($('#heap-chart')) drawChart(history.samples);
    if($('#signal-history')) $('#signal-history').innerHTML=history.samples.filter(sample=>Number.isFinite(sample.rssi_dbm)).slice(-12).reverse().map(sample=>`<div class="event"><strong>${escapeHtml(sample.rssi_dbm)} dBm</strong><small>${date(sample.time)}</small></div>`).join('') || '<p>No radio samples recorded yet.</p>';
  } catch(error) { if(state.selected===id) for(const selector of ['#chart-description','#events','#signal-history']) if($(selector))$(selector).textContent='Could not load observations. '+error.message; }
}
function drawChart(samples) {
  const canvas=$('#heap-chart'), points=samples.filter(sample=>Number.isFinite(sample.heap));
  $('#chart-description').textContent=points.length?`${points.length} observations · ${bytes(Math.min(...points.map(p=>p.heap)))} minimum · ${date(points[0].time)} to ${date(points.at(-1).time)}`:'Waiting for the first board observation. No history has been fabricated.';
  const width=canvas.clientWidth, height=175, ratio=window.devicePixelRatio||1; canvas.width=width*ratio; canvas.height=height*ratio;
  const context=canvas.getContext('2d');context.scale(ratio,ratio);context.strokeStyle='#e1e6ed';context.lineWidth=1;
  for(let row=0;row<4;row++){context.beginPath();context.moveTo(0,20+row*40);context.lineTo(width,20+row*40);context.stroke();}
  if(!points.length)return;
  const maximum=Math.max(...points.map(p=>p.heap))*1.1 || 1, first=points[0].time, span=points.at(-1).time-first || 1;
  context.strokeStyle='#075edb';context.fillStyle='#075edb';context.lineWidth=2;context.beginPath();
  points.forEach((point,index)=>{const x=8+(point.time-first)/span*(width-16),y=155-point.heap/maximum*135;index?context.lineTo(x,y):context.moveTo(x,y);});context.stroke();
  if(points.length===1){context.beginPath();context.arc(8,155-points[0].heap/maximum*135,4,0,Math.PI*2);context.fill();}
}
async function confirmAction(title,copy) {
  const dialog=$('#confirm');$('#confirm-title').textContent=title;$('#confirm-copy').textContent=copy;dialog.returnValue='cancel';dialog.showModal();
  return new Promise(resolve=>dialog.addEventListener('close',()=>resolve(dialog.returnValue==='accept'),{once:true}));
}
async function runJob(action,payload={}) {
  const id=state.selected; state.busy=true;
  try {
    const {job}=await api(devicePath(id)+'/action',{action,...payload});
    for (;;) {
      let result;
      try {result=await api('/api/jobs/'+job);} catch(error) {throw new Error('Lost contact while observing '+action+'. It may still be running. Inspect board status and Activity before retrying. '+error.message);}
      notice(result.progress.at(-1)?.message || `${action}: ${result.state}`);
      if(result.state==='failed')throw new Error(result.error+' (outcome: '+result.outcome+'). Inspect the board before retrying.');
      if(result.state==='complete'){notice(result.result.message);return result.result;}
      await new Promise(resolve=>setTimeout(resolve,1500));
    }
  } finally {state.busy=false;}
}
async function readLogs() {
  if(state.logBusy || !state.selected)return;
  const id=state.selected;state.logBusy=true;
  try {
    const reply=await api(devicePath(id)+'/logs?cursor='+state.cursor); if(state.selected!==id)return;
    if(state.boot && state.boot!==reply.boot_id){state.logs+='\n[Board rebooted]\n';state.cursor=0;state.boot=reply.boot_id;state.decoder=new TextDecoder();return;}
    state.boot=reply.boot_id;
    if(reply.lost){state.logs+='\n['+reply.lost+' bytes lost from device buffer]\n';state.decoder=new TextDecoder();}
    const raw=Uint8Array.from(reply.data_hex.match(/.{2}/g)||[],hex=>parseInt(hex,16));
    state.logs=(state.logs+state.decoder.decode(raw,{stream:true})).slice(-65536);state.cursor=reply.next;
    if($('#log-output')){$('#log-output').textContent=state.logs||'No diagnostic output yet.';$('#log-output').scrollTop=$('#log-output').scrollHeight;$('#log-state').textContent='Read at '+new Date().toLocaleTimeString();}
  } catch(error) {if($('#log-state'))$('#log-state').textContent=error.message+(state.follow?' · Retrying read…':'');}
  finally {state.logBusy=false;}
}
function download(name,body,type='application/octet-stream') {
  const url=URL.createObjectURL(new Blob([body],{type})),link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
document.addEventListener('click',async event=>{
  const button=event.target.closest('button'); if(!button)return;
  try {
    if((button.dataset.device || button.dataset.tab) && state.busy)throw new Error('Wait for the current board operation to finish.');
    if(button.dataset.fleetView){state.fleetView=button.dataset.fleetView;renderFleet();return;}
    if(button.dataset.device){chooseBoard(button.dataset.device);return;}
    if(button.dataset.tab){state.tab=button.dataset.tab;state.follow=false;enterSection();return;}
        const action=button.dataset.action;if(!action)return;
    if(action==='clear-filters'){state.filter='all';state.query='';renderNav();renderFleet();return;}
    if(action==='copy-command'){try{await navigator.clipboard.writeText(button.dataset.command);button.textContent='Copied';}catch{notice('Select and copy the command shown below.',true);}return;}
    if(action==='retry-connection'){await refresh();return;}
    if(action==='enroll'){$('#enroll').showModal();return;}
    if(action==='fresh'){const id=state.selected;button.disabled=true;const status=await api(devicePath(id)+'/status');const device=state.devices.find(d=>d.device_id===id);if(device)device.status=status;if(state.selected===id&&['Overview','Resources','Services','Channels','Network'].includes(state.tab))renderObservation();else button.disabled=false;notice('Board status refreshed.');return;}
    if(action==='read-logs'){await readLogs();return;}
    if(action==='follow'){state.follow=!state.follow;button.textContent=state.follow?'Stop following':'Follow logs';if(state.follow)await readLogs();return;}
    if(action==='export'){download(current().name+'-status.json',JSON.stringify(current(),null,2),'application/json');return;}
    if(state.busy)throw new Error('Wait for the current operation to finish.');
    if(['pause','recover','reboot','revoke'].includes(action)){
      const device=current();
      const descriptions={
        pause:['Pause application on '+device.name+'?', 'All application services stop. Resident management stays available. Recover the confirmed application when you want to run it again.'],
        recover:['Recover application on '+device.name+'?', 'Stop the current application and restore the last confirmed release. Application services briefly pause; resident management stays available.'],
        reboot:['Reboot '+device.name+'?', 'Restart the entire board. Its application and management connection will be interrupted until it reconnects.'],
        revoke:['Revoke enrollment for '+device.name+'?', 'This removes management access until new credentials are provisioned.']
      };
      if(!await confirmAction(...descriptions[action]))return;
      if(action==='revoke'){await api(devicePath(device.device_id)+'/revoke',{});state.selected=null;await refresh();}
      else {await runJob(action);await refresh();render();}
    }
  } catch(error){notice(error.message,true);button.disabled=false;}
});
$('#content').addEventListener('submit',async event=>{if(event.target.id!=='rename-form')return;event.preventDefault();try{await api(devicePath(state.selected)+'/rename',{name:new FormData(event.target).get('name')});await refresh();render();notice('Board renamed.');}catch(error){notice(error.message,true);}});
function chooseWorkspace(view) {
  if(state.busy){notice('Wait for the current board operation to finish.');return;}
  state.selected=null;state.tab=view;state.follow=false;enterSection();
}
$('#fleet-nav').onclick=()=>chooseWorkspace('Overview');
$('#connections-nav').onclick=()=>chooseWorkspace('Connections');
$('#board-switcher').onchange=event=>chooseBoard(event.target.value);
$('#content').addEventListener('input',event=>{if(event.target.id==='fleet-search'){const position=event.target.selectionStart;state.query=event.target.value;renderFleet();const input=$('#fleet-search');input.focus();input.setSelectionRange(position,position);}});
$('#content').addEventListener('change',event=>{if(event.target.id==='fleet-filter'){state.filter=event.target.value;renderFleet();$('#fleet-filter').focus();}});
$('#logout').onclick=async()=>{try{await api('/logout',{});showLogin();}catch(error){notice(error.message,true);}};
$('#login-form').onsubmit=async event=>{event.preventDefault();try{await api('/session',{token:$('#token').value});$('#token').value='';$('#login-error').textContent='';await refresh();}catch(error){$('#login-error').textContent=error.message;}};
let enrollment=null;
$('#enroll-form').onsubmit=async event=>{
  event.preventDefault();const fields=Object.fromEntries(new FormData(event.target));
  if(!enrollment || enrollment.device_id!==fields.device_id || enrollment.name!==fields.name)enrollment={...fields,token:Array.from(crypto.getRandomValues(new Uint8Array(32)),byte=>byte.toString(16).padStart(2,'0')).join('')};
  try{const result=await api('/api/enroll',enrollment);enrollment.certificate=result.certificate;$('#enroll-form').hidden=true;$('#enroll-result').hidden=false;await refresh();}catch(error){$('#enroll-error').textContent=error.message;}
};
$('#download-token').onclick=()=>download('relay.token',enrollment.token);
$('#download-cert').onclick=()=>download('relay-ca.pem',enrollment.certificate);
$('#enroll-close').onclick=()=>$('#enroll').close();
$('#enroll-done').onclick=()=>{$('#enroll').close();$('#enroll-form').reset();$('#enroll-form').hidden=false;$('#enroll-result').hidden=true;enrollment=null;};
setInterval(()=>{if(state.signedIn)refresh();},5000);
setInterval(()=>{if(state.signedIn && state.follow)readLogs();},1000);
(async()=>{
  const ticket=new URLSearchParams(location.hash.slice(1)).get('ticket');
  if(ticket){history.replaceState(null,'',location.pathname);try{await api('/session',{ticket});}catch(error){$('#login-error').textContent=error.message;return;}}
  readRoute();
  await refresh();
  render();
})();
