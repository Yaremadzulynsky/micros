#include "../generated/selftest_ipc.h"
#include <micros/service.h>
/* Explicit test graph only: send White once and require both TX completion and
 * the matching optical RX waveform through independent micros channels. */
typedef struct {micros_handle_t commands,results,frames;uint64_t due;uint32_t words[34],count,sequence;int sent,tx,rx,done;} state_t;
static micros_result_t init(const micros_service_args_t*a)
{
    state_t*s=a->arena;micros_result_t r=selftest_commands_open(a,&s->commands);
    if(!r)r=selftest_results_open(a,&s->results);
    return r?r:selftest_frames_open(a,&s->frames);
}
static micros_result_t start(const micros_service_args_t*a)
{state_t*s=a->arena;s->due=a->api->monotonic_us(a->context)+7000000;return 0;}
static micros_result_t step(const micros_service_args_t*a)
{
    state_t*s=a->arena;uint64_t now=a->api->monotonic_us(a->context);if(s->done)return 0;
    if(!s->sent && now>=s->due){
        selftest_commands_message_t c={.request_id=0x74657374,.code=0xbb44ff00};
        micros_result_t r=selftest_commands_publish(a,s->commands,&c);if(r)return r;
        s->sent=1;s->due=now+3000000;
    }
    selftest_results_message_t result;
    if(!selftest_results_read(a,s->results,&result) && result.request_id==0x74657374)
        s->tx=result.status==0 && result.code==0xbb44ff00;
    selftest_frames_message_t f;
    if(!selftest_frames_read(a,s->frames,&f) && s->sent && f.total_words==34 && !f.overflow){
        if(f.offset==0){s->count=0;s->sequence=f.sequence;}
        if(f.sequence==s->sequence && f.offset==s->count && s->count+f.words_count<=34){
            for(unsigned i=0;i<f.words_count;i++)s->words[s->count++]=f.words[i];
            if(s->count==34){
                uint32_t code=0;
                for(unsigned i=0;i<32;i++)if(((s->words[i+1]>>16)&32767)>1100)code|=1u<<i;
                unsigned leader=s->words[0]&32767;
                s->rx=code==0xbb44ff00 && leader>7500 && leader<10500;
            }
        }
    }
    if(s->tx && s->rx){
        const uint8_t text[]="IR SELFTEST PASS TX result and optical RX via channels\n";
        s->done=1;return a->api->debug_write(a->context,text,sizeof(text)-1);
    }
    if(s->sent && now>=s->due){
        const uint8_t text[]="IR SELFTEST FAIL missing TX result or optical RX\n";
        a->api->debug_write(a->context,text,sizeof(text)-1);return MICROS_ERROR_SERVICE;
    }
    return 0;
}
static micros_result_t stop(const micros_service_args_t*a)
{
    state_t*s=a->arena;if(s->commands)selftest_commands_close(a,s->commands);
    if(s->results)selftest_results_close(a,s->results);
    if(s->frames)selftest_frames_close(a,s->frames);
    return 0;
}
const micros_service_descriptor_t micros_descriptor={.struct_bytes=sizeof(micros_service_descriptor_t),
    .abi_major=MICROS_ABI_MAJOR,.abi_revision=MICROS_ABI_REVISION,.target=MICROS_BUILD_TARGET,
    .arena_bytes=sizeof(state_t),.arena_alignment=_Alignof(state_t),.stack_bytes=2048,
    .init=init,.start=start,.step=step,.stop=stop};
const micros_service_descriptor_t*micros_service_query(void){return &micros_descriptor;}
