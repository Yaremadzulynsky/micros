'use strict';
/* Public artifact-derived layout. No sample sizes and no inferred free-space totals. */
window.microsFlash = (() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const bytes = n => !Number.isFinite(n) ? 'Unavailable' : n < 1024 ? `${n} B` : n < 1048576 ? `${+(n/1024).toFixed(2)} KiB` : `${+(n/1048576).toFixed(2)} MiB`;
  const hex = n => '0x' + n.toString(16).toUpperCase();
  const names = {nvs:'NVS · settings',phy_init:'PHY initialization',otadata:'Firmware selection',factory:'Base firmware',ota_0:'Firmware image 0',ota_1:'Firmware image 1',services:'Services',activation:'Activation journal'};
  // Services share the website’s blue; names and segment details identify each allocation.
  function serviceClass() { return 'resource-service'; }
  function partitionClass(p){
    if(p.reservedCapacity)return 'flash-unallocated';
    if(p.name==='Unallocated flash')return 'flash-unallocated';
    if(p.name==='ota_0'||p.name==='factory')return 'flash-firmware-a';
    if(p.name==='ota_1')return 'flash-firmware-b';
    if(p.serviceOther||p.name==='services')return 'flash-service';
    return 'flash-system';
  }
  function segments(parts, total) {
    let end = 0;
    const result = [];
    for (const p of [...parts].sort((a,b) => a.offset-b.offset)) {
      if (!Number.isInteger(p.offset) || !Number.isInteger(p.size) || p.size<=0 || p.offset<end || p.offset+p.size>total) return [];
      if (p.offset>end) result.push({name:end===0?'Boot / reserved':'Unallocated flash',offset:end,size:p.offset-end,unknown:true});
      result.push(p); end=p.offset+p.size;
    }
    if (end<total) result.push({name:'Unallocated flash',offset:end,size:total-end,unknown:true});
    return result;
  }
  function servicesPeek(flash, partition) {
    const selected = flash.services?.slots;
    if (!Array.isArray(selected)) return '<p class="flash-note">Stored image sizes unavailable for this application.</p>';
    const valid = selected.every(s => Number.isInteger(s.slot) && s.slot>=0 && s.slot<4 && Number.isInteger(s.offset) && s.offset>=0 && s.reserved_bytes===(flash.services?.slot_bytes||16384) && Number.isInteger(s.image_bytes) && s.image_bytes>0 && s.image_bytes<=s.reserved_bytes && s.offset+s.reserved_bytes<=partition.size);
    if (!valid) return '<p class="flash-note">Stored image sizes unavailable.</p>';
    // Preserve physical positions, including all unattributed space, in the miniature.
    let cursor=0; const marks=[];
    for (const s of [...selected].sort((a,b)=>a.offset-b.offset)) {
      if (s.offset<cursor) return '<p class="flash-note">Stored image sizes unavailable.</p>';
      if (s.offset>cursor) marks.push(`<span class="flash-unknown" data-flash-weight="${s.offset-cursor}"></span>`);
      marks.push(`<span class="flash-image" data-flash-weight="${s.image_bytes}"></span>`);
      if (s.reserved_bytes>s.image_bytes) marks.push(`<span class="flash-reserved" data-flash-weight="${s.reserved_bytes-s.image_bytes}"></span>`);
      cursor=s.offset+s.reserved_bytes;
    }
    if (cursor<partition.size) marks.push(`<span class="flash-unknown" data-flash-weight="${partition.size-cursor}"></span>`);
    const slots=Array.from({length:4},(_,slot)=>selected.find(s=>s.slot===slot));
    return `<div class="flash-mini" role="img" aria-label="Physical services partition: selected image bytes, slot reservations, and other storage with unknown contents">${marks.join('')}</div>
      <div class="flash-axis"><span>${hex(partition.offset)}</span><span>${hex(partition.offset+partition.size)}</span></div>
      <div class="flash-peek-heading"><strong>Service slots</strong><span>${bytes(flash.services?.slot_bytes||16384)} each · enlarged</span></div>
      <div class="flash-slots">${slots.map((s,i)=>`<div class="flash-slot"><div class="flash-slot-track ${s?'':'flash-unknown'}">${s?`<span class="flash-image" data-flash-percent="${s.image_bytes/s.reserved_bytes*100}"></span>`:''}</div><span class="flash-slot-number">${i}</span></div>`).join('')}</div>
      <div class="flash-image-labels">${slots.map((s,i)=>`<div><span>${i} · ${s?esc(s.name):'Not selected'}</span><strong>${s?bytes(s.image_bytes):'Usage unknown'}</strong></div>`).join('')}</div>
      <div class="flash-key"><span><i class="flash-image"></i>Image bytes</span><span><i class="flash-reserved"></i>Reserved capacity</span><span><i class="flash-unknown"></i>Other / unknown</span></div>
      <p class="flash-note">Image sizes match the confirmed application. Unused slot capacity remains reserved.</p>`;
  }
  function render(status) {
    const flash=status.flash || {total_bytes:status.board?.flash_mb*1048576,partitions:[]};
    const total=flash.total_bytes;
    if (!Number.isFinite(total)||total<=0) return '';
    let parts=Array.isArray(flash.partitions)&&flash.partitions.length?segments(flash.partitions,total):[];
    const listed=[];
    parts=parts.flatMap(p=>{
      const slots=flash.services?.slots;
      if(p.name!=='services'||!Array.isArray(slots)||!slots.length)return [p];
      const ordered=[...slots].sort((a,b)=>a.offset-b.offset),expanded=[];
      let cursor=0;
      for(const s of ordered){
        if(!Number.isInteger(s.offset)||s.offset<cursor||s.reserved_bytes!==(flash.services?.slot_bytes||16384)||!Number.isInteger(s.image_bytes)||s.image_bytes<=0||s.image_bytes>s.reserved_bytes||s.offset+s.reserved_bytes>p.size)return [p];
        if(s.offset>cursor)expanded.push({name:'Other service storage',offset:p.offset+cursor,size:s.offset-cursor,serviceOther:true});
        const index=(status.services||[]).findIndex(item=>item.name===s.name);
        const number=index>=0?index+1:s.slot+1;
        expanded.push({name:s.name,offset:p.offset+s.offset,size:s.reserved_bytes,image:s,number});
        cursor=s.offset+s.reserved_bytes;
      }
      if(cursor<p.size)expanded.push({name:'Other service storage',offset:p.offset+cursor,size:p.size-cursor,serviceOther:true});
      listed.push(...expanded.filter(p=>p.image));
      return expanded;
    });
    return `<section class="panel flash-panel"><div class="memory-heading"><h2>Flash memory</h2><strong>${bytes(total)} total</strong></div>${parts.length?`<div class="flash-map" aria-label="Physical flash partition allocation">${parts.map((p,i)=>{
      const label=names[p.name]||p.name, service=p.name==='services';
      const active=status.base_ota?.version===1 && p.name==='ota_'+status.base_ota.slot;
      if(p.image)return `<div class="flash-segment flash-service-slot" data-flash-weight="${p.size}"><button type="button" class="flash-region ${serviceClass(p.name,status.services||flash.services?.slots||[])}" aria-label="${esc(p.name)}, ${bytes(p.image.image_bytes)} image, ${bytes(p.size)} reserved" aria-describedby="flash-peek-${i}"></button><div class="flash-tooltip" id="flash-peek-${i}" role="tooltip"><div class="memory-heading"><strong>${esc(p.name)}</strong><strong>${bytes(p.size)} reserved</strong></div><div class="flash-mini" role="img" aria-label="${bytes(p.image.image_bytes)} stored image within ${bytes(p.size)} slot"><span class="flash-image" data-flash-weight="${p.image.image_bytes}"></span><span class="flash-reserved" data-flash-weight="${p.size-p.image.image_bytes}"></span></div><div class="flash-axis"><span>${bytes(p.image.image_bytes)} image · ${(p.image.image_bytes/p.size*100).toFixed(1)}%</span><span>${bytes(p.size-p.image.image_bytes)} slot headroom</span></div><p class="flash-note">${hex(p.offset)}–${hex(p.offset+p.size)} · slot ${p.image.slot}. Image size matches the confirmed application. Headroom remains reserved to this slot.</p></div></div>`;
      if(p.serviceOther)return `<div class="flash-segment" data-flash-weight="${p.size}"><button type="button" class="flash-region flash-service" aria-label="Other service storage, ${bytes(p.size)}" aria-describedby="flash-peek-${i}"></button><div class="flash-tooltip" id="flash-peek-${i}" role="tooltip"><div class="memory-heading"><strong>Other service storage</strong><strong>${bytes(p.size)}</strong></div><p class="flash-note">${hex(p.offset)}–${hex(p.offset+p.size)} · metadata, unselected slots and other reserved storage. Contents and usage are not measured.</p></div></div>`;
      return `<div class="flash-segment" data-flash-weight="${p.size}"><button type="button" class="flash-region ${partitionClass(p)}" aria-label="${esc(label)}, ${bytes(p.size)}" aria-describedby="flash-peek-${i}"></button><div class="flash-tooltip" id="flash-peek-${i}" role="tooltip"><div class="memory-heading"><strong>${esc(label)}${active?' · running':''}</strong><strong>${bytes(p.size)}</strong></div>${service?servicesPeek(flash,p):`<p class="flash-note">${hex(p.offset)}–${hex(p.offset+p.size)} · ${esc(p.note||(p.unknown?'Contents unknown':'Reserved partition · usage unavailable'))}</p>`}</div></div>`;
    }).join('')}</div><div class="flash-axis"><span>0 · partition allocation</span><span>${bytes(total)}</span></div><div class="memory-legend" aria-label="Flash color legend">${[...new Map(parts.map(p=>[p.image||p.reservedCapacity?p.name:partitionClass(p),p])).values()].sort((a,b)=>(partitionClass(a)==='flash-system'?-1:a.name==='Unallocated flash'?2:a.serviceOther?1:0)-(partitionClass(b)==='flash-system'?-1:b.name==='Unallocated flash'?2:b.serviceOther?1:0)||a.offset-b.offset).map(p=>`<button class="legend-button" data-peek="flash-peek-${parts.indexOf(p)}" aria-label="Inspect ${esc(p.image||p.reservedCapacity?p.name:partitionClass(p)==='flash-system'?'System partitions':names[p.name]||p.name)}"><i class="${p.image?serviceClass(p.name,status.services||flash.services?.slots||[]):partitionClass(p)}"></i>${esc(p.image||p.reservedCapacity?p.name:partitionClass(p)==='flash-system'?'System partitions':names[p.name]||p.name)}</button>`).join('')}</div><div class="ram-allocation-note">Service slots widened for visibility · select or focus a segment for details</div>`:'<div class="memory-bar memory-bar-unavailable" aria-hidden="true"></div><p class="flash-note">Partition layout unavailable for this base.</p>'}</section>`;
  }
  function summary(status) {
    const flash=status.flash||{}, total=flash.total_bytes??status.board?.flash_mb*1048576;
    const known=Number.isSafeInteger(total)&&total>0;
    const parts=known&&Array.isArray(flash.partitions)&&flash.partitions.length?segments(flash.partitions,total):[];
    const reserved=parts.reduce((sum,p)=>sum+(p.unknown?0:p.size),0), unmapped=known?total-reserved:0;
    const labels=[[reserved,'reserved','flash-summary-reserved'],[unmapped,'unmapped','flash-summary-unmapped']].filter(([value])=>value>0);
    return `<div class="memory-summary-pool"><div class="memory-summary-heading"><h3>Flash</h3><span>${known?bytes(total)+' total':'Capacity unavailable'}</span></div>${parts.length?`<div class="memory-summary-bar" role="img" aria-label="Flash partition allocation: ${labels.map(([value,label])=>bytes(value)+' '+label).join(', ')}"><span class="flash-summary-reserved" data-flash-weight="${reserved}"></span><span class="flash-summary-unmapped" data-flash-weight="${unmapped}"></span></div><div class="memory-summary-legend">${labels.map(([value,label,style])=>`<span><i class="${style}"></i>${bytes(value)} ${label}</span>`).join('')}</div><p class="memory-summary-note">Partition allocation · stored-byte usage unknown</p>`:'<p class="memory-summary-unavailable">Partition layout unavailable.</p>'}</div>`;
  }
  function mount() {
    document.querySelectorAll('[data-flash-weight]').forEach(el=>{el.style.flex=el.dataset.flashWeight+' 1 0px';});
    document.querySelectorAll('[data-flash-percent]').forEach(el=>{el.style.width=el.dataset.flashPercent+'%';});
  }
  function positionPeek(segment) {
    const peek=segment.querySelector('.flash-tooltip');
    if (!peek) return;
    const anchor=segment.parentElement.getBoundingClientRect();
    peek.style.top='100%';peek.style.bottom='auto';peek.style.maxHeight='';
    const above=Math.max(0,anchor.top-12),below=Math.max(0,innerHeight-anchor.bottom-12);
    const up=peek.scrollHeight>below && above>below;
    if (up) {peek.style.top='auto';peek.style.bottom='100%';}
    peek.style.maxHeight=Math.max(40,up?above:below)+'px';
  }
  document.addEventListener('keydown',e=>{if(e.key==='Escape')document.querySelectorAll('.flash-segment').forEach(el=>el.classList.add('flash-dismissed'));});
  document.addEventListener('pointerover',e=>{const segment=e.target.closest('.flash-segment');if(segment&&!segment.contains(e.relatedTarget)){segment.classList.remove('flash-dismissed');positionPeek(segment);}});
  document.addEventListener('focusin',e=>{const segment=e.target.closest('.flash-segment');if(segment){segment.classList.remove('flash-dismissed');positionPeek(segment);}});
  document.addEventListener('click',e=>{const legend=e.target.closest('[data-peek]');if(legend){document.getElementById(legend.dataset.peek)?.previousElementSibling?.focus();return;}const segment=e.target.closest('.flash-segment');if(segment){segment.classList.remove('flash-dismissed');positionPeek(segment);}});
  return {render,summary,mount,serviceClass};
})();
