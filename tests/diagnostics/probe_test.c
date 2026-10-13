#include "fake.h"
#include "service.c"
static probe_report_message_t report(void) {
    assert(tails[4]);packet_t *p=&packets[4][tails[4]-1];probe_report_message_t r;
    assert(!micros_diagnostics_v1_ProbeReport_decode(p->bytes,p->size,&r));return r;
}
int main(void) {
    reset_fake();state_t state={0};micros_service_args_t a={.api=&api,.arena=&state};
    fail_open=4;assert(initialize(&a)==MICROS_ERROR_BUSY);assert(!stop(&a));assert(opened==closed);
    reset_fake();state=(state_t){0};assert(!initialize(&a));state.config.duration_ms=100;state.config.reads_per_step=2;assert(!start(&a));
    inject(1,NULL,0,MICROS_ERROR_MESSAGES_MISSED);
    const uint8_t malformed[]={0x80};inject(1,malformed,sizeof(malformed),0);
    /* Empty protobuf is a valid default message, not an empty channel. */
    inject(1,NULL,0,0);assert(!step(&a));assert(report().missed_events==1 && report().decode_errors==1 && !report().messages);
    assert(heads[1]==2);now+=10000;assert(!step(&a));assert(state.result.messages==1);
    now+=200000;assert(!step(&a));probe_report_message_t r=report();
    assert(r.done && r.reason==1 && r.messages==1 && r.max_silence_us==90000);
    assert(r.observed_us==101000 && r.last_received_us==11000);
    unsigned before=heads[1];inject(1,NULL,0,0);assert(!step(&a));assert(heads[1]==before);
    assert(!stop(&a));assert(!stop(&a));assert(opened==closed);
    reset_fake();state=(state_t){0};assert(!initialize(&a));assert(!start(&a));
    now+=10000000;assert(!step(&a));r=report();assert(r.done && !r.messages && r.max_silence_us==10000000);
    assert(!stop(&a));
    reset_fake();state=(state_t){0};assert(!initialize(&a));state.config.max_messages=1;assert(!start(&a));inject(1,NULL,0,0);
    assert(!step(&a));assert(report().reason==2 && report().messages==1);assert(!stop(&a));
    reset_fake();state=(state_t){0};assert(!initialize(&a));assert(!start(&a));inject(1,NULL,0,MICROS_ERROR_STALE_HANDLE);
    assert(!step(&a));assert(report().reason==3 && report().last_error==MICROS_ERROR_STALE_HANDLE);assert(!stop(&a));
    reset_fake();state=(state_t){0};assert(!initialize(&a));assert(!start(&a));fail_publish=4;assert(step(&a)==MICROS_ERROR_CAPACITY);assert(!stop(&a));
    puts("probe: silence, bounded reads, malformed/default messages, loss notifications, limits and cleanup passed");
}
