#include "../generated/console_ipc.h"
#include <micros/service.h>
/* An explicit transport endpoint. The physical console uses these owned ports;
 * the worker never reads their cursors. No GPIO, timing or IR hardware here. */
typedef struct {micros_handle_t commands,results,frames;} state_t;
static micros_result_t init(const micros_service_args_t*a)
{
    state_t*s=a->arena;micros_result_t r=console_commands_open(a,&s->commands);
    if(!r)r=console_results_open(a,&s->results);
    return r?r:console_frames_open(a,&s->frames);
}
static micros_result_t idle(const micros_service_args_t*a){(void)a;return 0;}
static micros_result_t stop(const micros_service_args_t*a)
{
    state_t*s=a->arena;
    if(s->commands)console_commands_close(a,s->commands);
    if(s->results)console_results_close(a,s->results);
    if(s->frames)console_frames_close(a,s->frames);
    return 0;
}
const micros_service_descriptor_t micros_descriptor={
    .struct_bytes=sizeof(micros_service_descriptor_t),.abi_major=MICROS_ABI_MAJOR,
    .abi_revision=MICROS_ABI_REVISION,.target=MICROS_BUILD_TARGET,
    .arena_bytes=sizeof(state_t),.arena_alignment=_Alignof(state_t),.stack_bytes=2048,
    .init=init,.start=idle,.step=idle,.stop=stop};
const micros_service_descriptor_t*micros_service_query(void){return &micros_descriptor;}
