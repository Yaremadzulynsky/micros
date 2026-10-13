export function initialFlow(){return {now:1,level:0,events:0,queue:[],consumerPaused:false,gap:false,error:false,raw:1,button:{initialized:true,valid:true,candidate:false,pressed:false,changed:0},target:false,bounce:null};}
export function deliver(state){
 if(state.consumerPaused||state.error)return state;
 if(state.gap)return {...state,error:true,level:0};
 return {...state,level:state.queue.reduce(level=>level^1,state.level),queue:[]};
}
function publish(state){
 const gap=state.gap||state.queue.length===4;
 return deliver({...state,events:state.events+1,queue:[...state.queue,state.now].slice(-4),gap});
}
export function flowReducer(state,action){
 if(action.type==='reset')return initialFlow();
 if(action.type==='clock')return publish({...state,now:state.now+action.interval});
 if(action.type==='pause-consumer')return deliver({...state,consumerPaused:!state.consumerPaused});
 if(action.type==='button-edge')return {...state,target:!state.target,bounce:0};
 if(action.type==='sample'){
  const index=state.bounce;
  const pressed=index!==null && index<4 && index%2===1?!state.target:state.target;
  const next={...state,now:state.now+5,raw:pressed?0:1,button:{...state.button},bounce:index===null?null:index+1};
  if(!next.button.initialized||next.button.candidate!==pressed){next.button.initialized=true;next.button.candidate=pressed;next.button.changed=next.now;}
  const confirmed=next.now-next.button.changed>=action.debounce&&(!next.button.valid||next.button.pressed!==pressed);
  if(confirmed){next.button.valid=true;next.button.pressed=pressed;}
  if(index!==null&&index>=4+action.debounce/5)next.bounce=null;
  return confirmed&&pressed?publish(next):next;
 }
 return state;
}
