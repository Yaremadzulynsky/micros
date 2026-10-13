import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {initialFlow,flowReducer as reduce} from './toggle-model.js';
import {toggleLessons} from './toggle-lessons.js';

test('clock events toggle once; queued events remain distinct',()=>{
 let s=initialFlow();
 s=reduce(s,{type:'clock',interval:500});assert.equal(s.level,1);
 s=reduce(s,{type:'pause-consumer'});
 for(let n=0;n<2;n++)s=reduce(s,{type:'clock',interval:500});
 assert.equal(s.level,1);assert.equal(s.queue.length,2);
 s=reduce(s,{type:'pause-consumer'});assert.equal(s.level,1);assert.equal(s.events,3);assert.equal(s.queue.length,0);
});
test('stream overflow stops the LED consumer instead of silently skipping toggles',()=>{
 let s=reduce(initialFlow(),{type:'pause-consumer'});
 for(let n=0;n<5;n++)s=reduce(s,{type:'clock',interval:500});
 assert.equal(s.queue.length,4);assert.equal(s.gap,true);
 s=reduce(s,{type:'pause-consumer'});assert.equal(s.error,true);assert.equal(s.level,0);
 assert.deepEqual(reduce(s,{type:'reset'}),initialFlow());
});
test('bounce, hold and release produce one event per confirmed press',()=>{
 for(const debounce of [10,30,100]){
  let s=initialFlow();
  const edge=()=>{s=reduce(s,{type:'button-edge'});for(let n=0;n<40;n++)s=reduce(s,{type:'sample',debounce});};
  edge();assert.equal(s.events,1);assert.equal(s.level,1);assert.equal(s.raw,0);
  for(let n=0;n<100;n++)s=reduce(s,{type:'sample',debounce});
  assert.equal(s.events,1);
  edge();assert.equal(s.events,1);assert.equal(s.raw,1);
  edge();assert.equal(s.events,2);assert.equal(s.level,0);
 }
});
test('both lessons show the same LED source; every note refers to an actual line',async()=>{
 assert.deepEqual(Object.keys(toggleLessons),['blink','button']);
 const led=Object.values(toggleLessons).map(l=>l.steps.find(s=>s.path==='services/led/src/service.c'));
 assert.ok(led.every(Boolean));assert.equal(led[1].reuse,true);
 for(const [id,lesson] of Object.entries(toggleLessons))for(const step of lesson.steps){
  if(!step.path)continue;
  const source=await readFile(new URL(`../../../examples/tutorials/toggle/${step.path}`,import.meta.url),'utf8');
  for(const [prefix] of step.notes||[])assert.ok(source.split('\n').some(line=>line.trim().startsWith(prefix)),`${id}: ${prefix}`);
 }
});

test('displayed source and download match the SDK example in this docs build',async()=>{
 const {createHash}=await import('node:crypto');
 const {readdir}=await import('node:fs/promises');
 const {inflateRawSync}=await import('node:zlib');
 const root=new URL('../../../build/docs-site/tutorials/',import.meta.url);
 const manifest=JSON.parse(await readFile(new URL('source.json',root),'utf8'));
 assert.equal(manifest.repository,'https://github.com/Yaremadzulynsky/micros');
 assert.match(manifest.revision,/^[a-f0-9]{40}$/);
 assert.equal(manifest.source,'examples/tutorials/toggle');
 assert.ok(Object.keys(manifest.files).length >= 16);
 const hash=b=>createHash('sha256').update(b).digest('hex');
 const files=(await readdir(new URL('toggle-example/',root),{recursive:true,withFileTypes:true})).filter(e=>e.isFile());
 assert.equal(files.length,Object.keys(manifest.files).length);
 const zip=await readFile(new URL('toggle-example.zip',root));
 assert.equal(hash(zip),manifest.archive_sha256);
 const archived=new Map();
 for(let offset=0;zip.readUInt32LE(offset)===0x04034b50;){
  assert.equal(zip.readUInt16LE(offset+6)&8,0,'No ZIP data descriptors');
  const method=zip.readUInt16LE(offset+8),size=zip.readUInt32LE(offset+18);
  const length=zip.readUInt16LE(offset+26),extra=zip.readUInt16LE(offset+28);
  const name=zip.subarray(offset+30,offset+30+length).toString();
  const start=offset+30+length+extra,data=zip.subarray(start,start+size);
  assert.ok([0,8].includes(method));
  archived.set(name,method===8?inflateRawSync(data):data);offset=start+size;
 }
 assert.equal(archived.size,Object.keys(manifest.files).length);
 for(const [name,digest]of Object.entries(manifest.files)){
  const source=await readFile(new URL('toggle-example/'+name,root));
  assert.equal(hash(source),digest,name);
  assert.deepEqual(archived.get('toggle-example/'+name),source,name);
 }
});

test('all lessons retain docs navigation and load content-versioned local assets',async()=>{
 const {createHash}=await import('node:crypto');
 for(const [page,id] of [['','index'],['blink/','blink'],['button/','button']]){
  const html=await readFile(new URL('../../../build/docs-site/tutorials/'+page+'index.html',import.meta.url),'utf8');
  assert.ok(html.includes('data-md-component="header"'));
  assert.ok(html.includes('data-md-component="tabs"'));
  assert.ok(html.includes('id="micros-tutorial" data-lesson="'+id+'"'));
  for(const extension of ['js','css']){
   const pattern=new RegExp('assets/tutorials/tutorial\\.([a-f0-9]{16})\\.'+extension);
   const match=html.match(pattern);assert.ok(match,extension+' must have a content hash');
   const bytes=await readFile(new URL('../../../build/docs-site/'+match[0],import.meta.url));
   assert.equal(match[1],createHash('sha256').update(bytes).digest('hex').slice(0,16));
  }
  assert.doesNotMatch(html,/<iframe|href="https:\/\/meetmicros.com\/tutorials/);
 }
});
