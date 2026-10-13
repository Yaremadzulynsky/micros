'use strict';
/* Render only board measurements and hash-verified labels. Missing data stays unavailable. */
window.microsInsights = (() => {
  const esc=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const size=value=>Number.isFinite(value)?(value<1024?value+' B':(value/1024).toFixed(1)+' KiB'):'Unavailable';
  const name=(service,index)=>service.name || 'Unnamed service '+(index+1);
  const table=(headers,rows)=>`<div class="table-wrap"><table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(cell=>`<td>${esc(cell)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  const panel=(title,copy,body)=>`<section class="panel"><h2>${title}</h2><p>${copy}</p>${body}</section>`;
  const detail=(title,copy,body)=>`<details class="detail-disclosure"><summary>${title}</summary><div class="disclosure-body"><p>${copy}</p>${body}</div></details>`;
  const unavailable=()=>panel('Diagnostics unavailable','This base predates resource telemetry. Update its base over USB to report these measurements.','');
  function resources(status) {
    if(!status.board)return window.microsMemory.render(status)+window.microsFlash.render(status)+unavailable();
    const services=status.services||[], board=status.board, memory=status.memory||{};
    const rows=board.gpio.map(resource=>{
      const owners=services.map((service,index)=>({service,index})).filter(({service})=>service.gpio_granted & (1<<resource.line));
      const opened=owners.filter(({service})=>service.gpio_open & (1<<resource.line));
      return [resource.name,'GPIO '+resource.pin,resource.output?'Output':'Input',owners.map(({service,index})=>name(service,index)).join(', ')||'Available',opened.length?'Open':'Not open',resource.level===1?'High':resource.level===0?'Low':'Unknown',board.recovery_pin===resource.pin?'Base recovery input at boot':'—'];
    });
    return window.microsMemory.render(status)+window.microsFlash.render(status)+detail('Hardware ownership',`${esc(board.profile)} · ${board.flash_mb} MiB flash. Grants come from the deployed application; open state comes from runtime handles.`,rows.length?table(['Resource','Pin','Direction','Granted to','Use','Level','Base reservation'],rows):'<p>This board definition exposes no GPIO resources.</p>')+
      detail('Service reservations','Arenas are reserved blocks; the runtime cannot measure allocations made privately inside them. Stack free is the lowest observed unused stack, not current free space.',table(['Service','Arena reserved','Stack reserved','Stack watermark','Timers open / limit','Handles open / limit'],services.map((s,i)=>[name(s,i),size(s.arena_reserved),size(s.stack_reserved),size(s.stack_free_bytes),`${s.timers_open??'—'} / ${s.timers_limit??'—'}`,`${s.handles_open??'—'} / ${s.handles_limit??'—'}`])))+
      detail('Resident base','Wi-Fi, TLS management, the supervisor and IPC storage belong to the base. They stay active with no application services.','<p>The service quotas above exclude these base tasks. Their memory is reflected in the board heap measurements.</p>');
  }
  function services(status) {
    const services=status.services||[];
    const copy=status.labels_source==='device_graph'?'Names and versions are reported by the board from its validated application graph.':status.labels_source==='verified_release'?'Names and versions match the reported base and confirmed graph hash.':'This server has no matching release metadata for the running application. Names return when its exact release records are published, or after a deployment through the configured micros CLI. Numbered services identify runtime order, not physical flash slots.';
    return panel('Service health',copy,services.length?table(['Service','Version','State','Result','Steps','Callbacks'],services.map((s,i)=>[name(s,i),s.version,s.state,s.result,s.steps,s.callbacks])):'<p>No application services loaded. Resident management remains active.</p>')+
      (status.board?detail('Execution timing','Maximum elapsed durations since this service instance loaded. These include scheduling delays; they are not CPU utilization. Timer lateness is delay beyond the scheduled deadline.',table(['Service','Longest hook (µs)','Longest callback (µs)','Maximum timer lateness (µs)'],services.map((s,i)=>[name(s,i),s.hook_max_us,s.callback_max_us,s.timer_late_max_us]))):'');
  }
  function channels(status) {
    if(!status.channels)return unavailable();
    const services=status.services||[], list=status.channels;
    return panel('Service communication','Relationships below are declared permissions. Backlog is the slowest open subscriber, capped at retained depth. Missed counts sum skips reported to subscribers; latest-value skips are expected coalescing.',list.length?table(['Channel','Publishers (granted)','Subscribers (granted)','Policy','Backlog / depth','Published','Missed / skipped','Last message age'],list.map(channel=>{
      const participants=field=>services.map((s,i)=>({s,i})).filter(({s})=>s[field]&(1<<(channel.key-1))).map(({s,i})=>name(s,i)).join(', ')||'None';
      return [channel.name||'Channel '+channel.key,participants('publish_mask'),participants('subscribe_mask'),channel.policy===1?'Stream':'Latest',channel.backlog+' / '+channel.depth,channel.published,channel.missed,channel.published?(channel.age_us/1e6).toFixed(1)+'s':'Never published'];
    })):'<p>No channels configured.</p>');
  }
  function network(status) {
    if(!status.network)return unavailable();
    const network=status.network;
    return panel('Network health','Measurements from the board’s Wi-Fi station. Counters reset on reboot and include deliberate disconnects during configuration.',table(['Measurement','Value'],[['Associated and addressed',network.connected?'Yes':'No'],['IP address',network.ip],['Wi-Fi RSSI',network.rssi_dbm==null?'Unavailable':network.rssi_dbm+' dBm'],['Disconnects since boot',network.disconnects],[status.platform==='samd21'?'Last disconnect reason':'Last disconnect reason (ESP-IDF code)',network.last_disconnect_reason??'Unavailable']]))+
      panel('Recent signal history','Last twelve retained observations; sampled every 30 seconds.','<div id="signal-history">Loading observations…</div>')+
      detail('Interpretation','Weak signal, repeated disconnects and shrinking heap can help explain missed check-ins. Correlate these observations with the Activity timeline.','<p>Server presence can lag by up to 30 seconds. An offline board cannot supply a fresh radio measurement.</p>');
  }
  return {Resources:resources,Services:services,Channels:channels,Network:network};
})();
