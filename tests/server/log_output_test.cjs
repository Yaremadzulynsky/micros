// Exercise the real log renderer with both supported device log semantics.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('src/server/web/app.js','utf8');
const code=source.slice(source.indexOf('async function readLogs()'),source.indexOf('\nfunction download('));
async function run(replies) {
 const elements={'#log-output':{textContent:'',scrollHeight:10},'#log-state':{textContent:''}};
 const state={selected:'board',logBusy:false,boot:null,cursor:0,logs:'',decoder:new TextDecoder()};
 const context=vm.createContext({state,TextDecoder,Uint8Array,Date,$:key=>elements[key],devicePath:()=>'',api:async()=>replies.shift()});
 vm.runInContext(code,context);
 while(replies.length) await vm.runInContext('readLogs()',context);
 return {state,elements};
}
(async()=>{
 let f=await run([{mode:'drain',data_hex:'68656c6c6f0a'},{mode:'drain',data_hex:''},{mode:'drain',data_hex:'616761696e0a'}]);
 assert.equal(f.state.logs,'hello\nagain\n');assert.equal(f.state.cursor,0);
 assert.equal(f.elements['#log-output'].textContent,f.state.logs);
 assert.match(f.elements['#log-state'].textContent,/^Read at /);
 f=await run([{boot_id:'a',data_hex:'6869',lost:2,next:4},{boot_id:'b',data_hex:'',lost:0,next:0}]);
 assert.match(f.state.logs,/2 bytes lost/);assert.match(f.state.logs,/Board rebooted/);
 assert.equal(f.state.cursor,0);
 console.log('Consuming embedded logs and cursor-based logs render correctly');
})().catch(error=>{console.error(error);process.exitCode=1;});
