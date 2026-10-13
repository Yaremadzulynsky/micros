'use strict';
/* Local permissions and confirmed remote routes, arranged with D3 Sankey.
   Every ribbon represents one permission, never a measured message rate. */
window.microsGraph = (() => {
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const mask=value=>Number.isInteger(value)&&value>=0&&value<=0xffffffff;
  let data=null, observer=null, ui={key:'',selected:null,zoom:1,x:0,y:0};
  function model(status) {
    const services=Array.isArray(status.services)?status.services:[], channels=Array.isArray(status.channels)?status.channels:[];
    const nodes=services.map((s,i)=>({id:'s'+i,kind:'service',name:s.name||'Unnamed service '+(i+1),detail:s.state||'State unavailable',remote:s.name==='board.network-bridge'})), edges=[];
    let incomplete=!Array.isArray(status.services)||!Array.isArray(status.channels);
    channels.forEach((c,index)=>{
      const id='c'+index, valid=Number.isInteger(c.key)&&c.key>=1&&c.key<=32&&channels.filter(other=>other.key===c.key).length===1;
      nodes.push({id,kind:'channel',name:c.name||'Channel '+(Number.isInteger(c.key)?c.key:'unknown'),detail:c.policy===1?'Stream':c.policy===2?'Latest value':'Mode unavailable'});
      if(!valid){incomplete=true;return;}
      services.forEach((s,i)=>{
        if(!mask(s.publish_mask)||!mask(s.subscribe_mask))incomplete=true;
        if(mask(s.publish_mask)&&(s.publish_mask&(1<<(c.key-1))))edges.push({id:'p'+i+'-'+index,from:'s'+i,to:id,kind:'publishes'});
        if(mask(s.subscribe_mask)&&(s.subscribe_mask&(1<<(c.key-1))))edges.push({id:'l'+i+'-'+index,from:id,to:'s'+i,kind:'listens'});
      });
      const remote=Array.isArray(status.remote_connections)?status.remote_connections:[];
      remote.forEach((connection,i)=>{
        if(connection.key!==c.key||!['publish','subscribe'].includes(connection.direction)||!connection.peer_device)return;
        const remoteId='r'+i,publisher=connection.direction==='publish';
        nodes.push({id:remoteId,kind:'remote',remote:true,name:connection.peer_name||connection.peer_device,
          detail:(publisher?'Remote publisher':'Remote listener')+' · '+(connection.state||'Unknown'),
          route:connection.route,reason:connection.reason});
        edges.push({id:'remote-'+i,from:publisher?remoteId:id,to:publisher?id:remoteId,
          kind:publisher?'publishes':'listens',remote:true,unavailable:connection.state!=='Ready'});
      });
    });
    return {nodes,edges,incomplete,reported:Array.isArray(status.channels),channels:channels.length};
  }
  function fleetModel(devices) {
    const valid=devices.filter(d=>/^[a-f0-9]{12}$/.test(d.device_id));
    const nodes=valid.map(d=>({id:'b'+d.device_id,kind:'board',board:d.device_id,name:d.name||d.device_id,
      detail:`${d.online?'Online':'Offline'} · ${Array.isArray(d.status?.services)?d.status.services.length+(d.status.services.length===1?' service':' services'):'Awaiting first report'}`,
      services:(d.status?.services||[]).map(s=>s.name||'Unnamed service').join(', ')}));
    const routes=new Map(),edges=[];
    const severity={Ready:0,Connecting:1,Offline:2,Unavailable:3,Unknown:4};
    let incomplete=valid.some(d=>!Array.isArray(d.status?.remote_connections));
    for(const device of valid)for(const c of (Array.isArray(device.status?.remote_connections)?device.status.remote_connections:[])){
      if(!['publish','subscribe'].includes(c.direction)||!/^[a-f0-9]{12}$/.test(c.peer_device)||!c.route||c.peer_device===device.device_id)continue;
      // The same route is reported at both ends. Channel names alone never join boards.
      const source=c.direction==='publish'?c.peer_device:device.device_id,target=c.direction==='publish'?device.device_id:c.peer_device;
      const key=JSON.stringify([c.route,source,target]);
      let state=Object.hasOwn(severity,c.state)?c.state:'Unknown';
      if(state==='Ready'&&valid.some(d=>[source,target].includes(d.device_id)&&!d.online))state='Offline';
      if(routes.has(key)){
        const route=routes.get(key);if(severity[state]>severity[route.state])route.state=state;
        continue;
      }
      if(!nodes.some(n=>n.id==='b'+c.peer_device))nodes.push({id:'b'+c.peer_device,kind:'board',remote:true,
        name:c.peer_name||c.peer_device,detail:'Outside this console'});
      routes.set(key,{source,target,name:c.route,kind:c.kind,state});
    }
    [...routes.entries()].sort(([a],[b])=>a.localeCompare(b)).forEach(([,r],i)=>{
      const id='c'+i;
      nodes.push({id,kind:'channel',name:r.name,detail:`${r.kind? r.kind[0].toUpperCase()+r.kind.slice(1)+' · ':''}${r.state}`});
      edges.push({id:'p'+i,from:'b'+r.source,to:id,kind:'publishes',unavailable:r.state!=='Ready'},
        {id:'l'+i,from:id,to:'b'+r.target,kind:'listens',unavailable:r.state!=='Ready'});
    });
    return {nodes,edges,incomplete,reported:true,channels:routes.size,fleet:true};
  }
  function render(status,online,board='') {
    return renderGraph(model(status),board,online);
  }
  function renderFleet(devices,fullPage=false) {
    return devices.length?renderGraph({...fleetModel(devices),fullPage},'fleet',true):'';
  }
  function renderGraph(graphData,board,online) {
    data=graphData;
    const key=JSON.stringify([board,data.nodes.map(n=>[n.id,n.name]),data.edges.map(e=>[e.id,e.from,e.to])]);
    if(key!==ui.key)ui={key,selected:null,zoom:1,x:0,y:0};
    const fleet=data.fleet,available=data.reported&&data.channels>0;
    const isolated=data.nodes.filter(n=>n.kind===(fleet?'board':'service')&&!data.edges.some(e=>e.from===n.id||e.to===n.id));
    const selection=fleet?'Select a board to trace its connections.':'Select a service, channel or remote endpoint to follow its flow.';
    const disconnected=fleet&&isolated.length?`<div class="fleet-unlinked"><p class="caption">${available?'Boards without reported cross-board routes':'Your boards'}</p><div class="fleet-unlinked-grid">${isolated.map(n=>`<button data-device="${esc(n.board)}" class="fleet-unlinked-board"><strong>${esc(n.name)}</strong><span>${esc(n.detail)}</span></button>`).join('')}</div></div>`:'';
    return `<section class="panel service-map graph-panel${fleet?' fleet-map':''}"><div class="panel-head"><div>${fleet&&data.fullPage?'<h1>Connections</h1>':`<h2>${fleet?'Board connections':'Service flow'}</h2>`}<p class="caption">${fleet?'Follow your application across the workbench.':online?'How services connect on this board.':'Last reported connections · board offline.'}</p></div>${fleet?`<span class="caption">${data.nodes.filter(n=>n.board).length} boards · ${data.channels} ${data.channels===1?'route':'routes'}</span>`:'<button class="text-button" data-tab="Channels">Inspect channels</button>'}</div>${available?`<div id="service-flow" class="service-flow"><p class="graph-mobile-hint">Swipe across to follow the flow →</p><div class="graph-viewport" tabindex="0" aria-label="${fleet?'Board connections':'Service flow'}: publishers to channels to listeners. Scroll to explore."></div><div class="graph-footer"><p class="graph-selection" aria-live="polite">${selection}</p>${fleet?'<button class="text-button" data-graph-open hidden>Open board</button>':''}<div class="graph-zoom" role="group" aria-label="Flow zoom"><button data-graph-action="out" aria-label="Zoom out">−</button><button data-graph-action="fit" aria-label="Reset flow view">Reset</button><button data-graph-action="in" aria-label="Zoom in">+</button></div></div><p class="graph-hint">${fleet?'Ribbons show configured routes, not measured traffic. A board can appear on both sides.':'Each ribbon is one configured connection, not a traffic measurement. Services can appear on both sides.'}${data.nodes.some(n=>n.remote)?fleet?' The globe marks a board outside this console.':' The globe marks remote access beyond this board.':''}${data.incomplete?fleet?' Route information is unavailable for some boards.':' Some permissions are unavailable.':''}</p>${!fleet&&isolated.length?`<p class="graph-isolated">No reported connections: ${isolated.map(n=>esc(n.name)).join(', ')}.</p>`:''}</div>`:`<p class="flow-empty">${fleet?'No cross-board routes have been reported yet. Open a board to explore its local services and channels.':data.reported?'No channels configured for this application.':'This board has not reported its channels.'}</p>`}${disconnected}</section>`;
  }
  function lines(label,limit=25) {
    const result=[];let rest=String(label);
    while(rest.length>limit){let cut=Math.max(rest.lastIndexOf('.',limit),rest.lastIndexOf('-',limit),rest.lastIndexOf(' ',limit));if(cut<limit/2)cut=limit;else cut+=1;result.push(rest.slice(0,cut));rest=rest.slice(cut);}
    result.push(rest);return result;
  }
  function layout(graphData,width=1000) {
    const compact=width<800;
    width=Math.max(680,width);
    const nodes=[],links=[],byId=new Map(graphData.nodes.map(n=>[n.id,n]));
    function add(id,original,role,missing=false) {
      let n=nodes.find(n=>n.id===id);
      if(!n){n={...original,id,originalId:original.id,role,missing,lines:lines(original.name)};nodes.push(n);}
      return n;
    }
    for(const channel of graphData.nodes.filter(n=>n.kind==='channel')){
      add(channel.id,channel,1);
      for(const role of [0,2]){
        const edges=graphData.edges.filter(e=>role===0?e.to===channel.id:e.from===channel.id);
        for(const edge of edges){
          const service=byId.get(role===0?edge.from:edge.to),id=(role===0?'p':'l')+service.id;
          add(id,service,role);
          links.push({...edge,source:role===0?id:channel.id,target:role===0?channel.id:id,channel:channel.id,value:1});
        }
        if(!edges.length){
          const id=(role===0?'p':'l')+channel.id;
          add(id,{id,name:graphData.incomplete?'Not reported':role===0?'No publisher connected':'No listener connected',detail:'',kind:'missing'},role,true);
          links.push({id:'missing-'+id,source:role===0?id:channel.id,target:role===0?channel.id:id,channel:channel.id,value:1,missing:true});
        }
      }
    }
    if(!nodes.length)return {width,height:0,nodes:[],links:[]};
    for(const node of nodes){
      node.fixedValue=Math.max(1,links.filter(l=>l.source===node.id).length,links.filter(l=>l.target===node.id).length);
    }
    const columns=[0,1,2].map(role=>nodes.filter(n=>n.role===role));
    const padding=Math.max(58,...nodes.map(n=>n.lines.length*17+24));
    const innerHeight=Math.max(...columns.map(column=>column.reduce((sum,n)=>sum+n.fixedValue*14,0)+(column.length-1)*padding));
    const result=window.microsSankey().nodeId(n=>n.id).nodeAlign(n=>n.role).nodeWidth(7).nodePadding(padding).extent([[compact?12:205,90],[width-(compact?12:205),90+innerHeight]]).iterations(32)({nodes,links});
    return {...result,width,height:innerHeight+155,compact};
  }
  const curve=link=>{const x0=link.source.x1,x1=link.target.x0,mid=(x0+x1)/2;return `M${x0},${link.y0} C${mid},${link.y0} ${mid},${link.y1} ${x1},${link.y1}`;};
  function trace(graphData,id) {
    const nodes=new Set(id?[id]:[]),edges=new Set();
    if(id)for(const direction of ['from','to']){
      const queue=[id],seen=new Set(queue),other=direction==='from'?'to':'from';
      while(queue.length){const current=queue.shift();for(const edge of graphData.edges)if(edge[direction]===current){edges.add(edge.id);nodes.add(edge[other]);if(!seen.has(edge[other])){seen.add(edge[other]);queue.push(edge[other]);}}}
    }
    return {nodes,edges};
  }
  function stop(){observer?.disconnect();observer=null;}
  function mount() {
    stop();const host=document.getElementById('service-flow');if(!host||!data)return;
    const viewport=host.querySelector('.graph-viewport'), graphData=data;
    let drawing,svg,drag;
    function size(){svg.setAttribute('width',drawing.width*ui.zoom);svg.setAttribute('height',drawing.height*ui.zoom);viewport.scrollLeft=ui.x;viewport.scrollTop=ui.y;host.querySelector('[data-graph-action="out"]').disabled=ui.zoom<=1;host.querySelector('[data-graph-action="in"]').disabled=ui.zoom>=2;}
    function highlight(id,pin=false) {
      if(pin)ui.selected=id;
      const connected=trace(graphData,id);
      svg.querySelectorAll('[data-graph-node]').forEach(el=>{el.classList.toggle('graph-dim',!!id&&!connected.nodes.has(el.dataset.graphNode));el.classList.toggle('graph-selected',el.dataset.graphNode===id);el.setAttribute('aria-pressed',String(el.dataset.graphNode===ui.selected));});
      svg.querySelectorAll('[data-graph-edge]').forEach(el=>{el.classList.toggle('graph-dim',!!id&&!connected.edges.has(el.dataset.graphEdge));el.classList.toggle('graph-traced',!!id&&connected.edges.has(el.dataset.graphEdge));});
      const node=graphData.nodes.find(n=>n.id===id),edges=graphData.edges;
      let detail=graphData.fleet?'Select a board to trace its connections.':'Select a service, channel or remote endpoint to follow its flow.';
      if(graphData.fleet&&node)detail=`${node.name} · ${node.detail}${node.services?' · '+node.services:''}`;
      else if(node?.kind==='channel'){
        const count=(direction,role)=>{
          const connections=edges.filter(e=>e[direction]===id),remote=connections.filter(e=>e.remote).length;
          return `${connections.length-remote} local ${role}${connections.length-remote===1?'':'s'}${remote?` · ${remote} remote ${role}${remote===1?'':'s'}`:''}`;
        };
        detail=`${node.name} · ${count('to','publisher')} · ${count('from','listener')}${graphData.incomplete?' · Partial report':''}`;
      }
      else if(node?.kind==='remote')detail=`${node.name} · ${node.detail} · ${node.route||'Configured route'} · ${node.reason||'Remote access through the coordination server'}`;
      else if(node)detail=`${node.name}${node.remote?' · Network bridge · Remote access':''} · ${node.detail} · Publishes to ${edges.filter(e=>e.from===id).length} · Listens to ${edges.filter(e=>e.to===id).length}`;
      host.querySelector('.graph-selection').textContent=detail;
      const open=host.querySelector('[data-graph-open]');
      if(open){open.hidden=!node?.board;if(node?.board){open.dataset.device=node.board;open.textContent='Open '+node.name;}}
    }
    function nodeSVG(node) {
      const center=(node.y0+node.y1)/2,isChannel=node.role===1,above=drawing.compact||isChannel;
      const detail=node.remote&&node.kind==='service'?`Remote access · ${node.detail}`:node.detail;
      const gap=node.remote?28:17;
      const textX=isChannel?(node.x0+node.x1)/2:drawing.compact?(node.role===0?node.x0:node.x1):node.role===0?node.x0-gap:node.x1+gap;
      const textY=above?node.y0-15-(node.lines.length-1)*17:center-(node.lines.length-1)*8.5-3;
      const anchor=isChannel?'middle':drawing.compact?(node.role===0?'start':'end'):node.role===0?'end':'start';
      const globe=node.remote?`<g class="graph-globe" transform="translate(${(node.x0+node.x1)/2} ${center})" aria-hidden="true"><circle r="13"/><ellipse rx="5.5" ry="13"/><path d="M-13 0H13M-11-6Q0-2 11-6M-11 6Q0 2 11 6"/></g>`:'';
      return `<g class="graph-node graph-${node.kind}" ${node.missing?'':`data-graph-node="${node.originalId}" role="button" tabindex="0" aria-label="${esc(node.name+', '+(isChannel?'channel':node.role===0?'publisher':'listener')+', '+detail+'. Trace connections')}" aria-pressed="false"`}><title>${esc(node.name+(detail?' · '+detail:''))}</title><rect class="graph-node-hit" x="${node.role===0?0:node.role===2?(drawing.compact?drawing.width-205:node.x0-8):textX-105}" y="${Math.min(textY-16,node.y0-8)}" width="${isChannel?210:205}" height="${Math.max(node.y1-textY+40,60)}" rx="5"/><rect class="graph-rail" x="${node.x0}" y="${node.y0}" width="7" height="${node.y1-node.y0}" rx="2"/>${globe}<text x="${textX}" y="${textY}" text-anchor="${anchor}" class="graph-node-name">${node.lines.map((line,i)=>`<tspan x="${textX}" dy="${i?17:0}">${esc(line)}</tspan>`).join('')}</text>${detail?`<text x="${textX}" y="${above?node.y1+20:textY+(node.lines.length-1)*17+20}" text-anchor="${anchor}" class="graph-node-detail">${esc(detail)}</text>`:''}</g>`;
    }
    function draw() {
      drawing=layout(graphData,viewport.clientWidth);
      viewport.innerHTML=`<svg class="service-flow-svg" viewBox="0 0 ${drawing.width} ${drawing.height}" role="group" aria-label="Publishers flow through named channels to listeners"><defs><linearGradient id="flow-publish" gradientUnits="userSpaceOnUse" x1="${drawing.compact?12:205}" x2="${drawing.width/2}"><stop stop-color="#7fa8dc"/><stop offset="1" stop-color="#c3d6ed"/></linearGradient><linearGradient id="flow-listen" gradientUnits="userSpaceOnUse" x1="${drawing.width/2}" x2="${drawing.width-(drawing.compact?12:205)}"><stop stop-color="#c3d6ed"/><stop offset="1" stop-color="#93b1d7"/></linearGradient></defs><text class="graph-column" x="0" y="25">${graphData.fleet?'PUBLISHING BOARDS':'PUBLISHERS'}</text><text class="graph-column" x="${drawing.width/2}" y="25" text-anchor="middle">${graphData.fleet?'CONNECTIONS':'CHANNELS'}</text><text class="graph-column" x="${drawing.width}" y="25" text-anchor="end">${graphData.fleet?'LISTENING BOARDS':'LISTENERS'}</text><path class="graph-direction" d="M${drawing.width*.29} 21h32m-5 -4l5 4 -5 4 M${drawing.width*.67} 21h32m-5 -4l5 4 -5 4"/>${drawing.links.map(link=>`<path class="graph-edge ${link.missing?'graph-missing-edge':link.unavailable?'graph-unavailable-edge':''}" data-graph-edge="${link.id}" ${link.missing?'':`data-flow-channel="${link.channel}"`} d="${curve(link)}" stroke="url(#flow-${link.source.role===0?'publish':'listen'})" stroke-width="${link.missing?1:link.unavailable?2:link.width}"><title>${esc(link.missing?link.source.missing?link.source.name:link.target.name:link.source.name+' → '+link.target.name)}</title></path>`).join('')}${drawing.nodes.map(nodeSVG).join('')}</svg>`;
      svg=viewport.querySelector('svg');size();highlight(ui.selected);
    }
    const targetId=target=>target.closest('[data-graph-node]')?.dataset.graphNode||target.closest('[data-flow-channel]')?.dataset.flowChannel;
    host.addEventListener('click',event=>{
      const action=event.target.closest('[data-graph-action]')?.dataset.graphAction;
      if(action){
        if(action==='fit'){ui.zoom=1;ui.x=0;ui.y=0;highlight(null,true);}
        else ui.zoom=Math.max(1,Math.min(2,ui.zoom+(action==='in'?.25:-.25)));
        size();return;
      }
      if(drag?.moved){drag=null;return;}
      const id=targetId(event.target);if(id)highlight(ui.selected===id?null:id,true);
    });
    viewport.addEventListener('pointerover',event=>{if(event.pointerType!=='touch'&&!ui.selected&&!drag){const id=targetId(event.target);if(id)highlight(id);}});
    viewport.addEventListener('pointerout',event=>{if(!ui.selected&&!drag&&!targetId(event.relatedTarget||viewport))highlight(null);});
    viewport.addEventListener('keydown',event=>{
      const id=targetId(event.target);
      if(id&&['Enter',' '].includes(event.key)){event.preventDefault();highlight(ui.selected===id?null:id,true);}
      if(event.key==='Escape')highlight(null,true);
    });
    viewport.addEventListener('scroll',()=>{ui.x=viewport.scrollLeft;ui.y=viewport.scrollTop;},{passive:true});
    viewport.addEventListener('pointerdown',event=>{
      drag=null;
      if(event.pointerType==='touch'||event.button!==0||targetId(event.target))return;
      drag={x:event.clientX,y:event.clientY,left:viewport.scrollLeft,top:viewport.scrollTop,moved:false};
      viewport.setPointerCapture(event.pointerId);viewport.classList.add('is-panning');
    });
    viewport.addEventListener('pointermove',event=>{if(drag){drag.moved=drag.moved||Math.abs(event.clientX-drag.x)+Math.abs(event.clientY-drag.y)>3;viewport.scrollLeft=drag.left+drag.x-event.clientX;viewport.scrollTop=drag.top+drag.y-event.clientY;}});
    const endDrag=()=>{viewport.classList.remove('is-panning');if(drag&&!drag.moved)drag=null;};
    viewport.addEventListener('pointerup',endDrag);viewport.addEventListener('pointercancel',()=>{drag=null;endDrag();});
    draw();let lastWidth=viewport.clientWidth;
    observer=new ResizeObserver(()=>{if(viewport.clientWidth!==lastWidth){lastWidth=viewport.clientWidth;draw();}});observer.observe(viewport);
  }
  return {model,fleetModel,render,renderFleet,mount,stop,layout,trace};
})();
