/* Deterministic fixture: actual generated codecs/lifecycle; bounded test bus and GPIO. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <micros/ipc.h>
#include "clock_hooks.h"
#include "button_hooks.h"
#include "led_hooks.h"
const micros_service_descriptor_t *clock_query(void), *button_query(void), *led_query(void);
uint32_t clock_toggle_binding(void){return 1;}
uint32_t button_toggle_binding(void){return 1;}
uint32_t led_toggle_binding(void){return 1;}
static struct {uint8_t bytes[16];uint32_t size;} ring[4];
static struct {uint32_t cursor,access;bool open;} ports[32];
static uint32_t next_port,published,opened,closed,level,input_level;
static uint64_t now,period,delay;
static bool input_open,output_open;
static micros_result_t read_error,write_error,publish_error;
static unsigned lost_logs;
static micros_timer_callback_t timer_callback;
static void *timer_data;
static uint64_t monotonic(micros_context_t *c){(void)c;return now;}
static micros_result_t open_port(micros_context_t *c,uint32_t key,uint32_t access,micros_handle_t *h){
 (void)c;assert(key==1 && next_port+1<32);*h=++next_port;ports[*h].open=true;ports[*h].access=access;
 ports[*h].cursor=published>4?published-4:0;opened++;return MICROS_OK;
}
static micros_result_t close_port(micros_context_t *c,micros_handle_t h){(void)c;assert(ports[h].open);ports[h].open=false;closed++;return MICROS_OK;}
static micros_result_t publish(micros_context_t *c,micros_handle_t h,const uint8_t *data,uint32_t size){
 (void)c;assert(ports[h].open && ports[h].access==MICROS_IPC_PUBLISH && size<=16);
 if(publish_error)return publish_error;
 memcpy(ring[published%4].bytes,data,size);ring[published%4].size=size;published++;return MICROS_OK;
}
static micros_result_t read_port(micros_context_t *c,micros_handle_t h,uint8_t *data,uint32_t capacity,uint32_t *size,micros_message_info_t *info){
 (void)c;assert(ports[h].open && ports[h].access==MICROS_IPC_SUBSCRIBE);memset(info,0,sizeof(*info));
 if(ports[h].cursor==published)return MICROS_ERROR_EMPTY;
 if(published-ports[h].cursor>4){info->messages_missed=published-ports[h].cursor-4;ports[h].cursor=published-4;return MICROS_ERROR_MESSAGES_MISSED;}
 unsigned index=ports[h].cursor%4;assert(capacity>=ring[index].size);*size=ring[index].size;
 memcpy(data,ring[index].bytes,*size);info->sequence=++ports[h].cursor;return MICROS_OK;
}
static micros_result_t timer_open(micros_context_t *c,uint64_t d,uint64_t p,micros_timer_callback_t fn,void *data,micros_handle_t *h){
 (void)c;assert(!timer_callback);timer_callback=fn;timer_data=data;delay=d;period=p;*h=100;opened++;return MICROS_OK;
}
static micros_result_t timer_close(micros_context_t *c,micros_handle_t h){(void)c;assert(h==100 && timer_callback);timer_callback=NULL;closed++;return MICROS_OK;}
static micros_result_t gpio_close(micros_context_t *c,micros_handle_t h){
 (void)c;if(h==101){assert(input_open);input_open=false;}else{assert(h==102 && output_open);output_open=false;}closed++;return MICROS_OK;
}
micros_result_t button_button_open(const micros_service_args_t *a,micros_handle_t *h){(void)a;assert(!input_open);input_open=true;*h=101;opened++;return MICROS_OK;}
micros_result_t button_button_read(const micros_service_args_t *a,micros_handle_t h,uint32_t *v){(void)a;assert(h==101 && input_open);if(read_error)return read_error;*v=input_level;return MICROS_OK;}
micros_result_t led_led_open(const micros_service_args_t *a,micros_handle_t *h){(void)a;assert(!output_open);output_open=true;*h=102;opened++;return MICROS_OK;}
micros_result_t led_led_write(const micros_service_args_t *a,micros_handle_t h,uint32_t v){(void)a;assert(h==102 && output_open && v<=1);if(write_error)return write_error;level=v;return MICROS_OK;}
static micros_result_t debug(micros_context_t *c,const uint8_t *data,uint32_t size){(void)c;assert(size>0 && data);lost_logs++;return MICROS_OK;}
static struct micros_ipc_api ipc={.ipc_open=open_port,.ipc_close=close_port,.ipc_publish=publish,.ipc_read=read_port};
static micros_api_t api={.monotonic_us=monotonic,.timer_open=timer_open,.timer_close=timer_close,.gpio_close=gpio_close,.debug_write=debug,._ipc=&ipc};
static void tick(micros_service_args_t *args,uint32_t input){input_level=input;now+=period;assert(timer_callback(args,100,timer_data)==MICROS_OK);}
static void reset(void){
 memset(ring,0,sizeof(ring));memset(ports,0,sizeof(ports));next_port=published=opened=closed=level=lost_logs=0;
 now=100;input_level=1;timer_callback=NULL;input_open=output_open=false;read_error=write_error=publish_error=0;
}
static void start(const micros_service_descriptor_t *d,micros_service_args_t *a){assert(d->init(a)==0);assert(d->start(a)==0);}
static void stop(const micros_service_descriptor_t *d,micros_service_args_t *a){assert(d->stop(a)==0);assert(d->stop(a)==0);}
static void clock_flow(const uint8_t *config,uint32_t size,uint64_t expected){
 reset();clock_context_t c={0};led_context_t l={0};
 micros_service_args_t ca={.api=&api,.arena=&c,.config_data=config,.config_bytes=size},la={.api=&api,.arena=&l};
 start(clock_query(),&ca);start(led_query(),&la);assert(period==expected && delay==expected && level==0);
 for(unsigned i=0;i<12;i++){tick(&ca,1);assert(led_query()->step(&la)==0 && level==((i+1)%2));assert(led_query()->step(&la)==0 && level==((i+1)%2));}
 /* Four retained events are read independently, not collapsed to latest. */
 for(unsigned i=0;i<4;i++)tick(&ca,1);
 for(unsigned i=0;i<4;i++)assert(led_query()->step(&la)==0 && level==((i+1)%2));
 /* GPIO and publisher failures propagate through real generated dispatch. */
 write_error=MICROS_ERROR_SERVICE;tick(&ca,1);assert(led_query()->step(&la)==MICROS_ERROR_SERVICE);write_error=0;
 publish_error=MICROS_ERROR_CAPACITY;now+=period;assert(timer_callback(&ca,100,timer_data)==MICROS_ERROR_CAPACITY);publish_error=0;
 stop(led_query(),&la);assert(level==0);start(led_query(),&la);
 for(unsigned i=0;i<4;i++)assert(led_query()->step(&la)==0 && level==0); /* retained old events ignored */
 tick(&ca,1);assert(led_query()->step(&la)==0 && level==1);
 for(unsigned i=0;i<5;i++)tick(&ca,1);
 assert(led_query()->step(&la)==MICROS_ERROR_MESSAGES_MISSED && lost_logs==1);
 stop(led_query(),&la);assert(level==0);stop(clock_query(),&ca);
 assert(opened==closed && !timer_callback && !output_open);
}
static void button_flow(void){
 reset();button_context_t b={0};led_context_t l={0};
 micros_service_args_t ba={.api=&api,.arena=&b},la={.api=&api,.arena=&l};
 start(button_query(),&ba);start(led_query(),&la);assert(period==5000 && delay==0);
 for(unsigned i=0;i<10;i++) { tick(&ba,1); }
 assert(published==0 && level==0);
 for(unsigned cycle=0;cycle<3;cycle++){
  tick(&ba,0);tick(&ba,1);tick(&ba,0);tick(&ba,1);tick(&ba,0);
  for(unsigned i=0;i<5;i++) { tick(&ba,0); }
  assert(published==cycle);
  tick(&ba,0);assert(published==cycle+1);assert(led_query()->step(&la)==0 && level==((cycle+1)%2));
  for(unsigned i=0;i<40;i++) { tick(&ba,0); }
  assert(published==cycle+1); /* hold */
  tick(&ba,1);tick(&ba,0);
  for(unsigned i=0;i<8;i++) { tick(&ba,1); }
  assert(published==cycle+1); /* release */
 }
 read_error=MICROS_ERROR_SERVICE;now+=period;assert(timer_callback(&ba,100,timer_data)==MICROS_ERROR_SERVICE);read_error=0;
 stop(button_query(),&ba);stop(led_query(),&la);assert(level==0 && opened==closed);
}
static void producer_swap(void){
 reset();clock_context_t c={0};button_context_t b={0};led_context_t l={0};
 micros_service_args_t ca={.api=&api,.arena=&c},ba={.api=&api,.arena=&b},la={.api=&api,.arena=&l};
 start(clock_query(),&ca);start(led_query(),&la);tick(&ca,1);assert(led_query()->step(&la)==0 && level==1);
 stop(clock_query(),&ca);start(button_query(),&ba);
 for(unsigned i=0;i<8;i++)tick(&ba,1);
 for(unsigned i=0;i<8;i++)tick(&ba,0);
 assert(led_query()->step(&la)==0 && level==0); /* unchanged LED context and subscription */
 stop(button_query(),&ba);stop(led_query(),&la);assert(opened==closed);
}
int main(void){const uint8_t configured[]={CLOCK_CONFIG_BYTES};clock_flow(NULL,0,500000);clock_flow(configured,sizeof(configured),250000);button_flow();producer_swap();puts("PASS: clock/button -> generated protobuf stream -> same LED; bounce, hold, release, queue gap, restart, errors, cleanup.");return 0;}
