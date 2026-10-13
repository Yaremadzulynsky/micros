#include "fake.h"
#include "service.c"
static replay_commands_message_t command(uint32_t op,uint32_t index,uint32_t offset,uint32_t count) {
    replay_commands_message_t c={.run_id=42,.operation=op,.index=index,.after_ms=offset,.count=count};
    c.schema_sha256.size=32;const char *hash=REPLAY_OUTPUT_SCHEMA_SHA256;
    for(unsigned i=0;i<32;i++){unsigned v;assert(sscanf(hash+2*i,"%2x",&v)==1);c.schema_sha256.bytes[i]=(uint8_t)v;}
    if(op==LOAD) {c.payload.size=2;c.payload.bytes[0]=0x28;c.payload.bytes[1]=(uint8_t)(index+1);}
    return c;
}
static void send(replay_commands_message_t c) {
    uint8_t b[128];uint32_t n;assert(!micros_diagnostics_v1_ReplayCommand_encode(&c,b,sizeof(b),&n));inject(2,b,n,0);
}
static void fresh(state_t *s,micros_service_args_t *a) {reset_fake();*s=(state_t){0};assert(!initialize(a));assert(!start(a));}
int main(void) {
    state_t s={0};micros_service_args_t a={.api=&api,.arena=&s};fresh(&s,&a);
    replay_commands_message_t c=command(LOAD,0,100,0);c.schema_sha256.bytes[0]^=1;send(c);assert(!step(&a));assert(!s.result.loaded_mask && s.result.rejected_commands==1);
    assert(!stop(&a));fresh(&s,&a);
    send(command(LOAD,0,100,0));send(command(LOAD,1,200,0));assert(!step(&a));assert(s.result.loaded_mask==3 && !tails[1]);
    send(command(LOAD,0,100,0));assert(!step(&a));assert(!s.result.rejected_commands);
    c=command(LOAD,0,100,0);c.payload.bytes[1]=99;send(c);assert(!step(&a));assert(s.result.rejected_commands==1);
    send(command(START,0,0,2));assert(!step(&a));assert(s.result.phase==RUNNING && !tails[1]);
    now+=100000;assert(!step(&a));assert(tails[1]==1 && s.result.published==1);
    now+=100000;assert(!step(&a));assert(tails[1]==2 && s.result.phase==COMPLETE);
    replay_output_message_t out;assert(!replay_output_decode(packets[1][1].bytes,packets[1][1].size,&out));assert(out.value==2);
    send(command(START,0,0,2));assert(!step(&a));assert(tails[1]==2);assert(!stop(&a));assert(!stop(&a));assert(opened==closed);
    fresh(&s,&a);send(command(LOAD,1,0,0));send(command(START,0,0,2));assert(!step(&a));assert(s.result.phase==1 && !tails[1]);assert(!stop(&a));
    fresh(&s,&a);send(command(LOAD,0,200,0));send(command(LOAD,1,100,0));assert(!step(&a));send(command(START,0,0,2));assert(!step(&a));assert(s.result.phase==1);assert(!stop(&a));
    fresh(&s,&a);c=command(LOAD,0,0,0);c.payload.size=1;c.payload.bytes[0]=0x80;send(c);assert(!step(&a));assert(!s.result.loaded_mask);assert(!stop(&a));
    fresh(&s,&a);now+=60000000;send(command(LOAD,0,0,0));assert(!step(&a));assert(s.result.phase==FAILED && !tails[1]);assert(!stop(&a));
    fresh(&s,&a);send(command(LOAD,0,100,0));send(command(START,0,0,1));assert(!step(&a));now+=500000;
    assert(!step(&a));assert(s.result.phase==FAILED && !tails[1] && s.result.max_late_us==400000);assert(!stop(&a));
    fresh(&s,&a);send(command(LOAD,0,0,0));send(command(START,0,0,1));fail_publish=1;assert(!step(&a));assert(s.result.phase==FAILED && !s.result.published);assert(!stop(&a));
    fresh(&s,&a);assert(!stop(&a));reset_fake();s=(state_t){0};fail_open=3;assert(initialize(&a)==MICROS_ERROR_BUSY);assert(!stop(&a));assert(opened==closed);
    puts("replay: schema fencing, ordered scheduling, partial loads, duplicate START, malformed input, timeout, lateness and cleanup passed");
}
