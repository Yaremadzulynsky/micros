const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = {window:{},structuredClone};
vm.runInNewContext(fs.readFileSync('src/server/web/sankey.min.js','utf8'),context);
vm.runInNewContext(fs.readFileSync('src/server/web/service-graph.js','utf8'),context);
const {model,layout,render,trace}=context.window.microsGraph;
const status={channels:[{key:2,name:'commands',policy:2},{key:1,name:'samples',policy:1}],services:[
  {name:'sensor <raw>',publish_mask:1,subscribe_mask:0,state:'Running'},
  {name:'processor',publish_mask:2,subscribe_mask:1,state:'Running'},
  {name:'logger',publish_mask:0,subscribe_mask:3,state:'Stopped'},
  {name:'recorder',publish_mask:1,subscribe_mask:1,state:'Running'}
]};
const graph=model(status),pairs=graph.edges.map(e=>e.from+'>'+e.to);
assert.equal(graph.nodes.length,6);
assert.equal(new Set(graph.nodes.map(n=>n.id)).size,6);
assert.equal(graph.nodes.filter(n=>n.name==='logger').length,1);
for(const pair of ['s0>c1','c1>s1','s1>c0','c0>s2','c1>s2','s3>c1','c1>s3'])assert(pairs.includes(pair),pair);
assert(!pairs.includes('s0>c0'));
assert.equal(graph.nodes.find(n=>n.id==='c0').detail,'Latest value');
assert.equal(graph.nodes.find(n=>n.id==='s2').detail,'Stopped');
for(const width of [320,800,1066]){
  const result=layout(graph,width);
  assert(result.width>=680&&result.height>0);
  assert.equal(result.links.filter(e=>!e.missing).length,graph.edges.length);
  for(const n of result.nodes)assert(Number.isFinite(n.x0)&&Number.isFinite(n.y0)&&n.x1>n.x0&&n.y1>n.y0);
  for(const e of result.links){
    assert.equal(e.value,1,'Connection width must not imply observed traffic');
    assert(e.source.role<e.target.role,'Every visual link reads left to right');
    assert(Number.isFinite(e.y0)&&Number.isFinite(e.y1)&&e.width>0);
  }
  assert.equal(new Set(result.nodes.map(n=>n.id)).size,result.nodes.length);
  assert.equal(result.nodes.filter(n=>n.originalId==='s3').length,2,'Duplex service appears in both roles');
  for(const role of [0,1,2]){
    const nodes=result.nodes.filter(n=>n.role===role).sort((a,b)=>a.y0-b.y0);
    for(let i=1;i<nodes.length;i++)assert(nodes[i].y0>=nodes[i-1].y1,'No overlapping nodes');
  }
}
const connected=trace(graph,'s1');
assert(connected.edges.has('p1-0'));assert(connected.edges.has('p0-1'));
assert(connected.edges.has('l3-1'),'Cycles terminate and preserve connected permissions');
const oneSide=layout(model({services:[{name:'sensor',publish_mask:1,subscribe_mask:0}],channels:[{key:1}]}));
assert.equal(oneSide.links.filter(e=>e.missing).length,1);
assert.equal(oneSide.nodes.find(n=>n.missing).name,'No listener connected');
const unknown=layout(model({services:[{}],channels:[{key:1}]}));
assert(unknown.nodes.filter(n=>n.missing).every(n=>n.name==='Not reported'));
for(const key of [0,33,-1,null]){const invalid=model({...status,channels:[{key}]});assert.equal(invalid.edges.length,0);assert(invalid.incomplete);}
assert.equal(model({...status,channels:[{key:1},{key:1}]}).edges.length,0);
const partial=model({channels:[{key:1}],services:[{publish_mask:1,subscribe_mask:0},{}]});
assert(partial.incomplete);assert.equal(partial.edges.length,1);
assert(render({channels:[]},true).includes('No channels configured'));
assert(render({},true).includes('has not reported its channels'));
assert(render(status,false).includes('Last reported connections · board offline'));
assert(render(status,true).includes('service-flow'));
const remoteStatus={...status,remote_connections:[
  {key:2,direction:'publish',peer_device:'a'.repeat(12),peer_name:'Control board',route:'commands',state:'Ready'},
  {key:1,direction:'subscribe',peer_device:'b'.repeat(12),peer_name:'Monitor board',route:'samples',state:'Offline'},
  {key:32,direction:'publish',peer_device:'c'.repeat(12)},
  {key:1,direction:'invalid',peer_device:'c'.repeat(12)}
]};
const remote=model(remoteStatus);
assert.equal(remote.nodes.filter(n=>n.kind==='remote').length,2);
assert(remote.edges.some(e=>e.from==='r0'&&e.to==='c0'&&!e.unavailable));
assert(remote.edges.some(e=>e.from==='c1'&&e.to==='r1'&&e.unavailable));
assert(trace(remote,'r0').edges.has('remote-0'));
for(const width of [320,800,1066]){
  const drawing=layout(remote,width);
  assert.equal(drawing.nodes.find(n=>n.originalId==='r0').role,0);
  assert.equal(drawing.nodes.find(n=>n.originalId==='r1').role,2);
  assert(drawing.links.every(e=>e.source.role<e.target.role&&Number.isFinite(e.width)));
}
assert(!graph.nodes.some(n=>n.kind==='remote'),'Missing local publishers never imply a remote route');
assert(render(remoteStatus,true).includes('globe marks remote access'));
const bridge=model({channels:[{key:1}],services:[{name:'board.network-bridge',publish_mask:1,subscribe_mask:1,state:'Stopped'}]});
assert.equal(bridge.nodes.find(n=>n.id==='s0').kind,'service','The bridge keeps its service identity');
assert.equal(bridge.nodes.find(n=>n.id==='s0').detail,'Stopped');
assert(layout(bridge).nodes.filter(n=>n.originalId==='s0').every(n=>n.remote));
console.log('Service flow: directed permissions, role layout, branches, cycles, missing endpoints and trace passed.');
