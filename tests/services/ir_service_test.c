#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>
static uint32_t rmt[1024],gpio[1024],dport[128];
#define IR_TEST_REGISTERS
#define R(o) rmt[(o)/4]
#define G(o) gpio[(o)/4]
#define D(o) dport[(o)/4]
#include "../../examples/services/ir-capture/src/service.c"
static uint64_t now;
static int queued,result_count,frame_count;
static ir_commands_message_t input;
static ir_results_message_t outcome;
static ir_frames_message_t frame;
static uint64_t clock_us(micros_context_t*c){(void)c;return now;}
static micros_result_t debug(micros_context_t*c,const uint8_t*p,uint32_t n){(void)c;(void)p;(void)n;return 0;}
static micros_result_t open_gpio(micros_context_t*c,uint32_t line,micros_handle_t*h){(void)c;*h=line+1;return 0;}
static micros_result_t close_gpio(micros_context_t*c,micros_handle_t h){(void)c;(void)h;return 0;}
#define OPEN(name,id) micros_result_t name(const micros_service_args_t*a,micros_handle_t*h){(void)a;*h=id;return 0;}
#define CLOSE(name) micros_result_t name(const micros_service_args_t*a,micros_handle_t h){(void)a;(void)h;return 0;}
OPEN(ir_commands_open,3) OPEN(ir_results_open,4) OPEN(ir_frames_open,5)
CLOSE(ir_commands_close) CLOSE(ir_results_close) CLOSE(ir_frames_close)
micros_result_t ir_commands_read(const micros_service_args_t*a,micros_handle_t h,ir_commands_message_t*c)
{(void)a;(void)h;if(!queued)return MICROS_ERROR_EMPTY;queued=0;*c=input;return 0;}
micros_result_t ir_results_publish(const micros_service_args_t*a,micros_handle_t h,const ir_results_message_t*c)
{(void)a;(void)h;outcome=*c;result_count++;return 0;}
micros_result_t ir_frames_publish(const micros_service_args_t*a,micros_handle_t h,const ir_frames_message_t*c)
{(void)a;(void)h;frame=*c;frame_count++;return 0;}
int main(void)
{
    state_t state={0};micros_api_t api={.monotonic_us=clock_us,.debug_write=debug,.gpio_close=close_gpio,.gpio_open=open_gpio};
    micros_service_args_t a={.arena=&state,.api=&api};
    assert(!initialize(&a));queued=1;input=(ir_commands_message_t){.request_id=99,.code=123};
    assert(!start(&a));assert(!queued && !state.busy); /* discard old retained command */
    R(0xa0)=0;input=(ir_commands_message_t){.request_id=1,.code=0xbb44ff00};queued=1;
    assert(!step(&a));assert(state.busy && state.last_id==1 && R(0x44)==(TXCFG|1));
    assert(MEM(256)==(9000u|0x8000|(4500u<<16)));
    for(unsigned i=0;i<32;i++)assert(MEM(257+i)==(560u|0x8000|((input.code&(1u<<i)?1690u:560u)<<16)));
    input.request_id=2;queued=1;assert(!step(&a));assert(outcome.status==1 && outcome.request_id==2);
    R(0xa0)=1u<<12;assert(!step(&a));assert(!state.busy && outcome.status==0 && outcome.request_id==1);
    input.request_id=1;queued=1;MEM(256)=123;assert(!step(&a));assert(outcome.status==4 && MEM(256)==123);
    R(0xa0)=0;input.request_id=3;queued=1;assert(!step(&a));now=200000;assert(!step(&a));assert(outcome.status==3 && !state.busy);
    MEM(0)=9000u|(4500u<<16)|0x80000000u;
    MEM(1)=560u|(1690u<<16)|0x80000000u;MEM(2)=560u;
    R(0xa0)=2;assert(!step(&a));assert(state.count==3);R(0xa0)=0;
    assert(!step(&a));assert(frame_count==1 && frame.total_words==3 && frame.words_count==3 && !frame.overflow);
    assert(frame.words[0]==(9000u|(4500u<<16)|0x80000000u));
    assert(!stop(&a));assert(!state.initialized);
    assert(result_count==4);puts("PASS IR lifecycle, NEC waveform, busy, completion, duplicate, timeout, frame channel, restart drain");
}
