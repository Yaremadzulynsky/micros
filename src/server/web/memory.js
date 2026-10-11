'use strict';
/* RAM pool measurements and service budgets are separate quantities. */
window.microsMemory = (() => {
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const valid=n=>Number.isFinite(n)&&n>=0;
  const size=n=>!valid(n)?'Unavailable':n<1024?`${n} B`:`${+(n/1024).toFixed(2)} KiB`;
  const available=(free,label)=>`<p class="ram-available"><strong>${size(free)}</strong><span>available ${label}</span></p>`;
  function internalPool(label,total,free,memory,services,diagnostics,status) {
    const used=total-free;
    let assigned=services.map((s,i)=>({...s,index:i,bytes:(s.arena_pool==='PSRAM'?0:s.arena_reserved)+s.stack_reserved}))
      .filter(s=>s.state==='Running'&&valid(s.arena_reserved)&&valid(s.stack_reserved)&&s.bytes>0);
    let reserved=assigned.reduce((sum,s)=>sum+s.bytes,0);
    if(reserved>used){assigned=[];reserved=0;}
    const items=assigned.map((s,i)=>({key:'service-'+s.index,label:s.name||'Unnamed service '+(s.index+1),bytes:s.bytes,service:s,number:i+1}));
    const a=status.heap_accounting;
    const accounted=a&&['ipc_storage','ipc_payload_capacity','ipc_assigned','runtime_metadata','supervisor_stack'].every(k=>Number.isInteger(a[k])&&a[k]>=0)&&a.ipc_storage>=a.ipc_payload_capacity&&a.ipc_payload_capacity>=a.ipc_assigned;
    if(accounted && reserved+a.ipc_storage+a.runtime_metadata+a.supervisor_stack<=used){
      if(a.ipc_storage)items.push({key:'communication',label:'Communication buffers',bytes:a.ipc_storage});
      if(a.runtime_metadata+a.supervisor_stack)items.push({key:'runtime',label:'Runtime',bytes:a.runtime_metadata+a.supervisor_stack});
      reserved+=a.ipc_storage+a.runtime_metadata+a.supervisor_stack;
    }
    if(used-reserved>0)items.push({key:'other',label:'Other heap usage',bytes:used-reserved});
    if(free>0)items.push({key:'free',label:'Free',bytes:free});
    function details(item){
      const s=item.service;
      if(item.key==='communication')return communications(status);
      if(item.key==='runtime')return `<div class="memory-heading"><strong>Runtime</strong><strong>${size(item.bytes)} allocated</strong></div><div class="flash-mini" role="img" aria-label="Runtime metadata and supervisor stack"><span class="ram-arena" data-flash-weight="${a.runtime_metadata}"></span><span class="ram-stack" data-flash-weight="${a.supervisor_stack}"></span></div><div class="ram-diagnostics"><div><span>Bookkeeping & task wrappers</span><strong>${size(a.runtime_metadata)}</strong></div><div><span>Supervisor stack</span><strong>${size(a.supervisor_stack)}</strong></div></div><p class="flash-note">Communication buffer storage is counted separately. Wi-Fi, TLS and other system allocations remain in Other heap usage.</p>`;
      if(!s)return `<div class="memory-heading"><strong>${item.label}</strong><strong>${size(item.bytes)}</strong></div>${diagnostics}<p class="flash-note">${item.key==='free'?'Available heap capacity. The largest block limits a single allocation.':'Heap usage outside the displayed allocations: Wi-Fi and TLS buffers, RTOS internals, allocation overhead and other unattributed memory. Individual sizes are not measured.'}</p>`;
      const peak=valid(s.stack_free_bytes)&&s.stack_free_bytes<=s.stack_reserved?s.stack_reserved-s.stack_free_bytes:null;
      return `<div class="memory-heading"><strong>${esc(item.label)}</strong><strong>${size(s.bytes)} reserved</strong></div><div class="ram-diagnostics"><div><span>Arena reserved · ${esc(s.arena_pool||'RAM')}</span><strong>${size(s.arena_reserved)}</strong></div><div><span>Current arena usage</span><strong>Not measured</strong></div><div><span>Stack reserved</span><strong>${size(s.stack_reserved)}</strong></div></div>${peak!==null&&s.stack_reserved>0?`<div class="flash-peek-heading"><strong>Stack peak</strong><span>${size(peak)} / ${size(s.stack_reserved)}</span></div><div class="flash-mini" role="img" aria-label="Stack peak ${size(peak)}, minimum unused ${size(s.stack_free_bytes)}"><span class="flash-image" data-flash-weight="${peak}"></span><span class="flash-reserved" data-flash-weight="${s.stack_free_bytes}"></span></div><div class="flash-axis"><span>Peak since start</span><span>${size(s.stack_free_bytes)} minimum unused</span></div>`:''}<p class="flash-note">${s.arena_pool==='PSRAM'?'This segment is the internal stack reservation; the arena is shown in PSRAM.':'This segment is reserved arena + stack capacity, not current in-service usage.'} Allocation overhead is included in Other heap usage.</p>`;
    }
    return `<div class="ram-pool"><div class="memory-heading"><h3>${label}</h3><strong>${size(used)} used · ${size(total)} total</strong></div>${available(free,'heap')}<div class="flash-map ram-map" aria-label="Internal heap allocation breakdown">${items.map(item=>`<div class="flash-segment" data-flash-weight="${item.bytes}"><button type="button" class="flash-region ${item.service?window.microsFlash.serviceClass(item.label,status.services||[]):item.key==='other'?'ram-other':item.key==='communication'?'ram-communication':item.key==='runtime'?'ram-runtime':'ram-free'}" aria-label="${esc(item.label)}, ${size(item.bytes)} ${item.service?'reserved':item.key==='free'?'free':'used'}" aria-describedby="ram-internal-${item.key}"></button><div class="flash-tooltip" id="ram-internal-${item.key}" role="tooltip">${details(item)}</div></div>`).join('')}</div><div class="ram-allocation-legend memory-legend">${items.map(item=>`<button class="legend-button" data-peek="ram-internal-${item.key}" aria-label="Inspect ${esc(item.label)}"><i class="${item.service?'flash-service-color':item.key==='other'?'ram-other':item.key==='communication'?'ram-communication':item.key==='runtime'?'ram-runtime':'ram-free'}"></i>${item.key==='free'?size(free)+' free':esc(item.label)}</button>`).join('')}</div><div class="ram-allocation-note">Service reservations · logical allocation, not physical partitions</div></div>`;
  }
  function communications(status){
    const a=status.heap_accounting;
    const channels=(status.channels||[]).filter(c=>Number.isInteger(c.depth)&&c.depth>0&&Number.isInteger(c.payload_bytes)&&c.payload_bytes>=0&&Number.isInteger(c.retained_bytes)&&c.retained_bytes>=0&&c.retained_bytes<=c.depth*c.payload_bytes);
    const complete=channels.length===(status.channels||[]).length;
    const retained=complete?channels.reduce((n,c)=>n+c.retained_bytes,0):null;
    return `<div class="memory-heading"><strong>Communication buffers</strong><strong>${size(a.ipc_storage)} allocated</strong></div><div class="ram-diagnostics"><div><span>Fixed payload capacity</span><strong>${size(a.ipc_payload_capacity)}</strong></div><div><span>Queue metadata</span><strong>${size(a.ipc_storage-a.ipc_payload_capacity)}</strong></div><div><span>Retained message data</span><strong>${size(retained)}</strong></div></div><div class="flash-peek-heading"><strong>Channel reservations</strong><span>${size(a.ipc_assigned)} assigned</span></div><div class="ram-services">${channels.map(c=>{const capacity=c.depth*c.payload_bytes;return `<div class="ram-service"><div class="ram-service-heading"><span>${esc(c.name||'Channel '+c.key)}</span><span>${size(c.retained_bytes)} data / ${size(capacity)} reserved</span></div>${capacity?`<div class="flash-mini" role="img" aria-label="${esc(c.name||'Channel '+c.key)} retained ${size(c.retained_bytes)} of ${size(capacity)}"><span class="flash-image" data-flash-weight="${c.retained_bytes}"></span><span class="flash-reserved" data-flash-weight="${capacity-c.retained_bytes}"></span></div>`:''}<div class="ram-peak">${c.depth} message slots × ${size(c.payload_bytes)} · backlog ${c.backlog??'unknown'}</div></div>`;}).join('')}</div><p class="flash-note">${size(a.ipc_payload_capacity-a.ipc_assigned)} payload capacity not assigned to channels. Empty and already-read buffers still reserve RAM.</p>`;
  }
  function psramPool(total,free,services){
    const owned=services.filter(s=>s.arena_pool==='PSRAM'&&s.state==='Running'&&valid(s.arena_reserved)&&s.arena_reserved>0);
    const used=total-free,reserved=owned.reduce((n,s)=>n+s.arena_reserved,0);
    if(reserved>used)return null;
    const segments=owned.map(s=>({name:s.name,bytes:s.arena_reserved,service:true}));
    if(used>reserved)segments.push({name:'Other PSRAM usage',bytes:used-reserved});
    if(free)segments.push({name:'Free',bytes:free,free:true});
    return `<div class="ram-pool"><div class="memory-heading"><h3>PSRAM</h3><strong>${size(used)} used · ${size(total)} total</strong></div>${available(free,'PSRAM')}<div class="flash-map ram-map" aria-label="PSRAM allocation breakdown">${segments.map((s,i)=>`<div class="flash-segment ${s.service?'flash-service-slot':''}" data-flash-weight="${s.bytes}"><button class="flash-region ${s.service?window.microsFlash.serviceClass(s.name,services):s.free?'ram-free':'ram-other'}" aria-label="${esc(s.name)}, ${size(s.bytes)} in PSRAM" aria-describedby="psram-detail-${i}"></button><div class="flash-tooltip" role="tooltip" id="psram-detail-${i}"><div class="memory-heading"><strong>${esc(s.name)} · PSRAM</strong><strong>${size(s.bytes)}</strong></div><p class="flash-note">${s.service?'Arena allocated in PSRAM. Current usage inside the arena is not measured. Its stack remains in internal RAM.':s.free?'Available PSRAM capacity.':'Other PSRAM allocations and allocator overhead.'}</p></div></div>`).join('')}</div><div class="memory-legend">${segments.map(s=>`<span><i class="${s.service?window.microsFlash.serviceClass(s.name,services):s.free?'ram-free':'ram-other'}"></i>${esc(s.name)} · ${size(s.bytes)}</span>`).join('')}</div></div>`;
  }
  function pool(label,key,memory,services,status) {
    const total=memory[key+'_total'],free=memory[key+'_free'],known=valid(total)&&total>0&&valid(free)&&free<=total;
    const disabled=total===0,used=known?total-free:null;
    const summary=disabled?'Not enabled':valid(total)?size(total)+' total':'Capacity unavailable';
    const diagnostics=key==='internal'?`<div class="ram-diagnostics"><div><span>Minimum free since boot</span><strong>${size(memory.internal_min)}</strong></div><div><span>Largest free block</span><strong>${size(memory.internal_largest)}</strong></div></div>`:'';
    function tooltip(kind) {
      return `<div class="flash-tooltip" id="ram-${key}-${kind}" role="tooltip"><div class="memory-heading"><strong>${label} · ${kind}</strong><strong>${known?size(kind==='used'?used:free):summary}</strong></div>${known?`<div class="flash-mini" role="img" aria-label="${size(used)} used and ${size(free)} free"><span class="ram-other" data-flash-weight="${used}"></span><span class="ram-free" data-flash-weight="${free}"></span></div><div class="flash-axis"><span>${size(used)} used</span><span><i class="ram-other"></i>Other heap usage</span><span><i class="ram-free"></i>${size(free)} free</span></div>`:''}${diagnostics}${kind==='used'&&key==='psram'?'<p class="flash-note">Per-service PSRAM usage is unavailable.</p>':''}${!known?`<p class="flash-note">${disabled?'This pool is not enabled.':'Usage measurements are unavailable.'}</p>`:''}</div>`;
    }
    if (key==='psram' && known && services.some(s=>s.arena_pool==='PSRAM')) {const result=psramPool(total,free,services);if(result)return result;}
    if (key==='internal' && known) return internalPool(label,total,free,memory,services,diagnostics,status);
    return `<div class="ram-pool"><div class="memory-heading"><h3>${label}</h3><strong>${summary}</strong></div>${known?available(free,key==='internal'?'heap':'PSRAM'):''}<div class="flash-map ram-map" aria-label="${label} usage">${known?[['used',used],['free',free]].filter(([,n])=>n>0).map(([kind,n])=>`<div class="flash-segment" data-flash-weight="${n}"><button type="button" class="flash-region ${kind==='used'?'ram-other':'ram-free'}" aria-label="${label} ${kind}, ${size(n)}" aria-describedby="ram-${key}-${kind}"></button>${tooltip(kind)}</div>`).join(''):`<div class="flash-segment" data-flash-weight="1"><button type="button" class="flash-region flash-unknown" aria-label="${label}, ${summary}" aria-describedby="ram-${key}-unavailable"></button>${tooltip('unavailable')}</div>`}</div>${known?`<div class="memory-legend"><span><i class="ram-other"></i>${size(used)} used</span><span><i class="ram-free"></i>${size(free)} free</span></div>`:''}</div>`;
  }
  function render(status) {
    const memory=status.memory||{};
    return `<section class="panel ram-panel"><h2>Heap / RAM</h2>${pool('Internal heap','internal',memory,status.services||[],status)}${pool('PSRAM','psram',memory,status.services||[],status)}</section>`;
  }
  function summary(status) {
    const memory=status.memory||{};
    function usage(label,total,free) {
      const known=valid(total)&&total>0&&valid(free)&&free<=total;
      const used=known?total-free:null;
      return `<div class="memory-summary-pool"><div class="memory-summary-heading"><h3>${label}</h3><span>${valid(total)&&total>0?size(total)+' total':'Capacity unavailable'}</span></div>${known?`<div class="memory-summary-bar" role="img" aria-label="${label}: ${size(used)} used, ${size(free)} free, ${size(total)} total"><span class="memory-summary-used" data-flash-weight="${used}"></span><span class="memory-summary-free" data-flash-weight="${free}"></span></div><div class="memory-summary-legend"><span><i class="memory-summary-used"></i>${size(used)} used</span><span><i class="memory-summary-free"></i>${size(free)} free</span></div>`:`<p class="memory-summary-unavailable">${!valid(total)&&valid(free)?size(free)+' free. Usage unavailable.':'Usage unavailable.'}</p>`}</div>`;
    }
    const internalFree=Object.hasOwn(memory,'internal_free')?memory.internal_free:status.heap;
    return usage('Internal RAM',memory.internal_total,internalFree)+(valid(memory.psram_total)&&memory.psram_total>0?usage('PSRAM',memory.psram_total,memory.psram_free):'');
  }
  return {render,summary};
})();
