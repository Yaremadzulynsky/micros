#include "../diagnostics/fake.h"
#include "service.c"
static shell_demo_status_message_t report(void)
{
    assert(tails[2]);
    packet_t *p = &packets[2][tails[2]-1];
    shell_demo_status_message_t message;
    assert(!micros_example_shell_ValueStatus_decode(p->bytes, p->size, &message));
    return message;
}
int main(void)
{
    reset_fake(); state_t state = {0}; micros_service_args_t a = {.api=&api, .arena=&state};
    fail_open=2; assert(initialize(&a)==MICROS_ERROR_BUSY); assert(!stop(&a)); assert(opened==closed);
    reset_fake(); state=(state_t){0}; assert(!initialize(&a)); assert(!start(&a));
    assert(!step(&a)); assert(report().value==0 && report().accepted==0);
    uint8_t valid[]={8,42}, invalid[]={8,101}, malformed[]={0x80}, zero[]={8,0};
    inject(1,valid,sizeof(valid),0); inject(1,invalid,sizeof(invalid),0);
    assert(!step(&a)); assert(heads[1]==1 && report().value==42 && report().accepted==1);
    assert(!step(&a)); assert(report().value==42 && report().rejected==1);
    inject(1,malformed,sizeof(malformed),0); assert(!step(&a)); assert(report().rejected==2);
    inject(1,NULL,0,MICROS_ERROR_MESSAGES_MISSED); assert(!step(&a)); assert(report().gaps==1);
    inject(1,zero,sizeof(zero),0); assert(!step(&a)); assert(report().value==0 && report().accepted==2);
    unsigned before=tails[2]; assert(!step(&a)); assert(tails[2]==before);
    now+=1000000; assert(!step(&a)); assert(tails[2]==before+1);
    assert(!stop(&a)); assert(!stop(&a)); assert(opened==closed);
    puts("shell example: typed commands, service-side bounds, malformed messages, loss and cleanup passed");
}
