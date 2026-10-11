#include "fake.h"
#include "service.c"
static void fresh(state_t *s,micros_service_args_t *a) {reset_fake();*s=(state_t){0};assert(!initialize(a));s->config.pre_samples=2;s->config.post_samples=2;assert(!start(a));}
static void sample(micros_service_args_t *a,uint32_t value) {level=value;assert(!step(a));now+=10000;}
int main(void) {
    state_t s={0};micros_service_args_t a={.api=&api,.arena=&s};fresh(&s,&a);
    sample(&a,0);sample(&a,0);sample(&a,0);sample(&a,1);sample(&a,1);sample(&a,0);
    assert(s.result.triggered && s.result.reason==1 && s.result.retained==5 && !s.result.done);
    while(!s.result.done) { assert(!step(&a)); }
    assert(tails[1]==2);
    unsigned count=0;
    for(unsigned i=0;i<2;i++) {
        recorder_records_message_t v;packet_t *p=&packets[1][i];assert(!micros_diagnostics_v1_CaptureRecord_decode(p->bytes,p->size,&v));
        assert(v.first_index==count && v.total==5);
        for(unsigned j=0;j<v.samples_count;j++,count++) {
            assert(v.samples[j].index==count && v.samples[j].sequence==count+2 && v.samples[j].trigger==(count==2));
        }
    }
    assert(count==5);
    assert(!stop(&a));assert(!stop(&a));assert(opened==closed);
    fresh(&s,&a);sample(&a,0);gpio_error=MICROS_ERROR_BUSY;sample(&a,1);gpio_error=0;sample(&a,1);
    assert(!s.result.triggered && s.result.read_errors==1); // No invented edge across an invalid sample.
    now+=10000000;
    while(!s.result.done) { assert(!step(&a)); }
    assert(s.result.reason==2 && s.result.retained==2);assert(!stop(&a));
    fresh(&s,&a);s.config.pre_samples=0;now+=10000000;assert(!step(&a));assert(s.result.done && !s.result.retained && !tails[1]);assert(!stop(&a));
    fresh(&s,&a);sample(&a,0);now+=50000;sample(&a,0);assert(s.result.skipped_scans==5 && s.result.attempts==2);assert(!stop(&a));
    fresh(&s,&a);s.config.trigger=0;s.config.post_samples=0;sample(&a,1);assert(s.result.done && s.result.retained==1);assert(!stop(&a));
    fresh(&s,&a);s.config.trigger=0;s.config.post_samples=0;fail_publish=1;level=1;assert(step(&a)==MICROS_ERROR_CAPACITY);assert(!stop(&a));
    reset_fake();s=(state_t){0};fail_open=2;assert(initialize(&a)==MICROS_ERROR_BUSY);assert(!stop(&a));assert(opened==closed);
    puts("recorder: pre/post trigger chronology, invalid readings, timeout, skipped scans and cleanup passed");
}
