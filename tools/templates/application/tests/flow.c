/* Test-only bus: actual generated protobuf codecs and service lifecycle run above it. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <micros/ipc.h>
#include "climate_hooks.h"
#include "fan_hooks.h"
#include "display_hooks.h"
const micros_service_descriptor_t *climate_query(void), *fan_query(void), *display_query(void);
uint32_t climate_climate_reading_binding(void) { return 1; }
uint32_t fan_climate_reading_binding(void) { return 1; }
uint32_t fan_fan_status_binding(void) { return 2; }
uint32_t display_climate_reading_binding(void) { return 1; }
uint32_t display_fan_status_binding(void) { return 2; }
static struct { uint8_t data[32]; uint32_t bytes, revision; } channels[3];
static struct { uint32_t channel, cursor, access; bool open; } handles[16];
static uint32_t next_handle, opened, closed, messages;
static uint64_t now, interval;
static micros_timer_callback_t timer_callback;
static void *timer_data;
static char last_log[128];
static uint64_t monotonic(micros_context_t *ctx) { (void)ctx; return now; }
static micros_result_t open_port(micros_context_t *ctx, uint32_t key, uint32_t access, micros_handle_t *out)
{
    (void)ctx; assert(key == 1 || key == 2); assert(next_handle+1 < 16);
    *out = ++next_handle; handles[*out].channel=key; handles[*out].access=access;
    handles[*out].open=true; opened++; return MICROS_OK;
}
static micros_result_t close_port(micros_context_t *ctx, micros_handle_t h)
{ (void)ctx; assert(handles[h].open); handles[h].open=false; closed++; return MICROS_OK; }
static micros_result_t publish(micros_context_t *ctx, micros_handle_t h, const uint8_t *data, uint32_t bytes)
{
    (void)ctx; assert(handles[h].open && handles[h].access == MICROS_IPC_PUBLISH);
    uint32_t key=handles[h].channel; assert(bytes <= sizeof(channels[key].data));
    memcpy(channels[key].data,data,bytes); channels[key].bytes=bytes; channels[key].revision++;
    return MICROS_OK;
}
static micros_result_t read_port(micros_context_t *ctx, micros_handle_t h, uint8_t *data,
                                uint32_t capacity, uint32_t *bytes, micros_message_info_t *info)
{
    (void)ctx; assert(handles[h].open && handles[h].access == MICROS_IPC_SUBSCRIBE);
    uint32_t key=handles[h].channel;
    if (handles[h].cursor==channels[key].revision) return MICROS_ERROR_EMPTY;
    assert(capacity>=channels[key].bytes); *bytes=channels[key].bytes;
    memcpy(data,channels[key].data,*bytes); handles[h].cursor=channels[key].revision;
    memset(info,0,sizeof(*info)); return MICROS_OK;
}
static micros_result_t timer_open(micros_context_t *ctx, uint64_t delay, uint64_t period,
                                 micros_timer_callback_t cb, void *data, micros_handle_t *out)
{
    (void)ctx; assert(delay==interval && period==interval);
    timer_callback=cb; timer_data=data; *out=15; opened++; return MICROS_OK;
}
static micros_result_t timer_close(micros_context_t *ctx, micros_handle_t h)
{ (void)ctx; assert(h==15 && timer_callback); timer_callback=NULL; closed++; return MICROS_OK; }
static micros_result_t log_write(micros_context_t *ctx, const uint8_t *data, uint32_t size)
{
    (void)ctx; assert(size<sizeof(last_log)); memcpy(last_log,data,size); last_log[size]=0;
    messages++; return MICROS_OK;
}
static void run(const uint8_t *config, uint32_t bytes, uint64_t period)
{
    memset(channels,0,sizeof(channels)); memset(handles,0,sizeof(handles));
    next_handle=opened=closed=messages=0; now=0; interval=period;
    struct micros_ipc_api ipc={.ipc_open=open_port,.ipc_close=close_port,.ipc_publish=publish,.ipc_read=read_port};
    micros_api_t api={.monotonic_us=monotonic,.timer_open=timer_open,.timer_close=timer_close,.debug_write=log_write,._ipc=&ipc};
    climate_context_t climate={0}; fan_context_t fan={0}; display_context_t display={0};
    micros_service_args_t args[3]={{.api=&api,.arena=&climate,.config_data=config,.config_bytes=bytes},
                                 {.api=&api,.arena=&fan},{.api=&api,.arena=&display}};
    const micros_service_descriptor_t *services[3]={climate_query(),fan_query(),display_query()};
    for (unsigned i=0;i<3;i++) { assert(services[i]->init(&args[i])==MICROS_OK); assert(services[i]->start(&args[i])==MICROS_OK); }
    const int temperatures[]={20000,22000,24000,26000,28000,30000,28000,26000,24000,22000};
    for (unsigned i=0;i<20;i++) {
        now+=period; assert(timer_callback(&args[0],15,timer_data)==MICROS_OK);
        unsigned before=messages;
        assert(services[2]->step(&args[2])==MICROS_OK); assert(messages==before); /* No matching fan reply yet. */
        assert(services[1]->step(&args[1])==MICROS_OK);
        assert(services[2]->step(&args[2])==MICROS_OK); assert(messages==before+1);
        unsigned phase=i%10; bool enabled=phase>=4 && phase<=7;
        char expected[128];
        snprintf(expected,sizeof(expected),"Simulated climate #%u: temp=%d mC humidity=%u permille fan=%s\n",
                 i+1,temperatures[phase],450+(unsigned)(temperatures[phase]-20000)/200,enabled?"ON":"OFF");
        assert(!strcmp(last_log,expected));
        assert(services[2]->step(&args[2])==MICROS_OK && messages==before+1);
    }
    /* A slow display skips samples; it does not consume the fan's subscription. */
    for (unsigned i=0;i<5;i++) {
        now+=period; assert(timer_callback(&args[0],15,timer_data)==MICROS_OK);
        assert(services[1]->step(&args[1])==MICROS_OK);
    }
    assert(services[2]->step(&args[2])==MICROS_OK);
    assert(strstr(last_log,"#25: temp=28000") && strstr(last_log,"fan=ON"));
    now+=6000000; assert(services[2]->step(&args[2])==MICROS_OK);
    assert(strstr(last_log,"stale data")); unsigned before=messages;
    assert(services[2]->step(&args[2])==MICROS_OK && messages==before);
    now+=period; assert(timer_callback(&args[0],15,timer_data)==MICROS_OK);
    assert(services[1]->step(&args[1])==MICROS_OK && services[2]->step(&args[2])==MICROS_OK);
    assert(strstr(last_log,"#26: temp=30000") && !display.state.stale);
    fan.config.off_millicelsius=fan.config.on_millicelsius;
    assert(fan_on_start(&fan)==MICROS_ERROR_INVALID_ARGUMENT);
    for (unsigned i=0;i<3;i++) {
        assert(services[i]->stop(&args[i])==MICROS_OK);
        assert(services[i]->stop(&args[i])==MICROS_OK);
    }
    assert(opened==closed && !timer_callback);
}
int main(void)
{
    const uint8_t configured[]={CONFIG_BYTES};
    run(NULL,0,1000000); run(configured,sizeof(configured),250000);
    return 0;
}
