#include "../generated/ir_resources.h"
#include "../generated/ir_ipc.h"
#include <micros/service.h>
/* ESP32 RMT: RX0 owns blocks 0-3; TX4 owns block 4. This graph must
 * be the only RMT user. 80MHz APB / 80 = one microsecond per envelope tick. */
#ifndef IR_TEST_REGISTERS
#define R(o) (*(volatile uint32_t *)(uintptr_t)(0x3ff56000u+(o)))
#define G(o) (*(volatile uint32_t *)(uintptr_t)(0x3ff44000u+(o)))
#define D(o) (*(volatile uint32_t *)(uintptr_t)(0x3ff00000u+(o)))
#endif
#define MEM(i) R(0x800+4*(i))
#define RXCFG ((1u<<17)|(1u<<5)|(1u<<7)|(80u<<8))
#define TXCFG ((1u<<17)|(1u<<19))
_Static_assert(IR_RX_GPIO_PIN==27 && IR_TX_GPIO_PIN==25,"ESP32 wiring mismatch");
typedef struct {
    micros_handle_t rx,tx,commands,results,frames;
    uint64_t deadline,captured_us;
    uint32_t sequence,count,position,raw[256],last_id;
    uint32_t routes[2],saved[7];
    ir_commands_message_t pending;
    int initialized,busy,overflow;
} state_t;
static void logtext(const micros_service_args_t*a,const char*t)
{ unsigned n=0;while(t[n])n++;a->api->debug_write(a->context,(const uint8_t*)t,n); }
static void arm(void)
{
    R(0x24)=RXCFG;
    for(unsigned i=0;i<256;i++)MEM(i)=0;
    R(0xac)=6;R(0x24)=RXCFG|4;R(0x24)=RXCFG|2;
}
static micros_result_t report(const micros_service_args_t*a,ir_commands_message_t c,uint32_t status)
{
    state_t*s=a->arena;
    ir_results_message_t result={.request_id=c.request_id,.code=c.code,.status=status};
    return ir_results_publish(a,s->results,&result);
}
static micros_result_t initialize(const micros_service_args_t*a)
{
    state_t*s=a->arena; micros_result_t r;
    if((r=ir_rx_open(a,&s->rx)) || (r=ir_tx_open(a,&s->tx)) ||
       (r=ir_commands_open(a,&s->commands)) || (r=ir_results_open(a,&s->results))) return r;
    return ir_frames_open(a,&s->frames);
}
static micros_result_t start(const micros_service_args_t*a)
{
    state_t*s=a->arena;
    s->routes[0]=G(0x27c);s->routes[1]=G(0x594);
    D(0xc0)|=1u<<9;D(0xc4)&=~(1u<<9);
    const unsigned offsets[]={0x20,0x24,0x40,0x44,0xc0,0xf0,0xa8};
    for(unsigned i=0;i<7;i++)s->saved[i]=R(offsets[i]);
    s->initialized=1;
    R(0xf0)|=1;R(0xa8)&=~((7u<<12)|7u);
    G(0x27c)=27|(1u<<7);G(0x594)=91|(1u<<10);
    R(0x20)=80|(20000u<<8)|(4u<<24)|(1u<<31);
    R(0x40)=80|(1u<<24)|(1u<<28)|(1u<<29)|(1u<<31);
    R(0xc0)=(1404u<<16)|701u;R(0x44)=TXCFG;
    s->busy=0;s->last_id=0;s->sequence=s->count=s->position=0;arm();
    /* A restart must not replay retained commands from the old subscriber. */
    ir_commands_message_t discarded;
    for(unsigned i=0;i<9;i++)if(ir_commands_read(a,s->commands,&discarded)==MICROS_ERROR_EMPTY)break;
    logtext(a,"IR SERVICE READY rx=27 tx=25 channels=commands,results,frames\n");return 0;
}
static micros_result_t step(const micros_service_args_t*a)
{
    state_t*s=a->arena;micros_result_t r;uint64_t now=a->api->monotonic_us(a->context);
    if(s->busy && ((R(0xa0)&(1u<<12)) || now>=s->deadline)) {
        unsigned status=(R(0xa0)&(1u<<12))?0:3;
        R(0x44)=TXCFG;s->busy=0;
        if((r=report(a,s->pending,status)))return r;
    }
    ir_commands_message_t command={0};r=ir_commands_read(a,s->commands,&command);
    if(!r) {
        if(!command.request_id)r=report(a,command,2);
        else if(command.request_id==s->last_id)r=report(a,command,4);
        else if(s->busy)r=report(a,command,1);
        else {
            MEM(256)=9000|0x8000|(4500u<<16);
            for(unsigned i=0;i<32;i++)MEM(257+i)=560|0x8000|((command.code&(1u<<i)?1690u:560u)<<16);
            MEM(289)=560|0x8000;MEM(290)=0;
            s->pending=command;s->last_id=command.request_id;s->deadline=now+150000;s->busy=1;
            R(0x44)=TXCFG|8;R(0x44)=TXCFG;R(0xac)=1u<<12;R(0x44)=TXCFG|1;
        }
        if(r)return r;
    } else if(r!=MICROS_ERROR_EMPTY) {
        logtext(a,"IR command rejected or missed; not replayed\n");
    }
    if(s->position<s->count) {
        ir_frames_message_t frame={.sequence=s->sequence,.monotonic_us=s->captured_us,
            .offset=s->position,.total_words=s->count,.overflow=s->overflow};
        while(s->position<s->count && frame.words_count<20)
            frame.words[frame.words_count++]=s->raw[s->position++];
        return ir_frames_publish(a,s->frames,&frame);
    }
    unsigned flags=R(0xa0);
    if(flags&6) {
        R(0x24)=RXCFG;s->position=s->count=0;s->overflow=(flags&4)!=0;
        for(unsigned i=0;i<256;i++) {
            uint32_t word=MEM(i);if(!(word&32767))break;
            s->raw[s->count++]=word;if(!((word>>16)&32767))break;
        }
        if(s->count>2 || s->overflow) {s->sequence++;s->captured_us=now;}
        else s->count=0;
        arm();
    }
    return 0;
}
static micros_result_t stop(const micros_service_args_t*a)
{
    state_t*s=a->arena;
    if(s->initialized) {
        R(0x24)=RXCFG;R(0x44)=TXCFG;G(0xc)=1u<<25;
        G(0x594)=s->routes[1];G(0x27c)=s->routes[0];
        const unsigned offsets[]={0x20,0x24,0x40,0x44,0xc0,0xf0,0xa8};
        for(unsigned i=0;i<7;i++)R(offsets[i])=s->saved[i];
        s->initialized=0;
    }
    if(s->commands)ir_commands_close(a,s->commands);
    if(s->results)ir_results_close(a,s->results);
    if(s->frames)ir_frames_close(a,s->frames);
    if(s->rx)a->api->gpio_close(a->context,s->rx);
    if(s->tx)a->api->gpio_close(a->context,s->tx);
    return 0;
}
const micros_service_descriptor_t micros_descriptor={
    .struct_bytes=sizeof(micros_service_descriptor_t),.abi_major=MICROS_ABI_MAJOR,
    .abi_revision=MICROS_ABI_REVISION,.target=MICROS_BUILD_TARGET,
    .arena_bytes=sizeof(state_t),.arena_alignment=_Alignof(state_t),.stack_bytes=2048,
    .init=initialize,.start=start,.step=step,.stop=stop};
const micros_service_descriptor_t*micros_service_query(void){return &micros_descriptor;}
