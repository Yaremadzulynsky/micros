/* Test-only transport: production generated codecs still encode/decode all bytes. */
#include <micros/service.h>
#include "micros/ipc.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

typedef struct { uint8_t bytes[256]; uint32_t size; micros_result_t error; } packet_t;
static packet_t packets[8][128];
static unsigned heads[8], tails[8], opened, closed, fail_open, fail_publish;
static uint64_t now = 1000;
static uint32_t level;
static micros_result_t gpio_error;
static void reset_fake(void) {
    memset(heads,0,sizeof(heads)); memset(tails,0,sizeof(tails));
    opened=closed=fail_open=fail_publish=0;now=1000;level=0;gpio_error=0;
}
static void inject(unsigned key, const uint8_t *bytes, uint32_t size, micros_result_t error) {
    assert(key<8 && tails[key]<128 && size<=256);
    packet_t *p=&packets[key][tails[key]++];p->size=size;p->error=error;
    if (size) memcpy(p->bytes,bytes,size);
}
static micros_result_t ipc_open(micros_context_t *c,uint32_t key,uint32_t access,micros_handle_t *h) {
    (void)c;(void)access;if (key==fail_open) return MICROS_ERROR_BUSY;
    ++opened;*h=key;return 0;
}
static micros_result_t ipc_close(micros_context_t *c,micros_handle_t h) {(void)c;(void)h;++closed;return 0;}
static micros_result_t ipc_publish(micros_context_t *c,micros_handle_t h,const uint8_t *b,uint32_t n) {
    (void)c;if (h==fail_publish) return MICROS_ERROR_CAPACITY;inject(h,b,n,0);return 0;
}
static micros_result_t ipc_read(micros_context_t *c,micros_handle_t h,uint8_t *b,uint32_t cap,uint32_t *n,micros_message_info_t *info) {
    (void)c;(void)info;if(heads[h]==tails[h]) return MICROS_ERROR_EMPTY;
    packet_t *p=&packets[h][heads[h]++];if(p->error)return p->error;
    assert(cap>=p->size);if(p->size)memcpy(b,p->bytes,p->size);*n=p->size;return 0;
}
static uint64_t monotonic(micros_context_t *c) {(void)c;return now;}
static micros_result_t gpio_open(micros_context_t *c,uint32_t line,micros_handle_t *h) {(void)c;(void)line;++opened;*h=7;return 0;}
static micros_result_t gpio_read(micros_context_t *c,micros_handle_t h,uint32_t *v) {(void)c;(void)h;*v=level;return gpio_error;}
static const struct micros_ipc_api ipc = {.ipc_open=ipc_open,.ipc_close=ipc_close,.ipc_publish=ipc_publish,.ipc_read=ipc_read};
static const micros_api_t api = {.monotonic_us=monotonic,._ipc=&ipc,.gpio_open=gpio_open,.gpio_close=ipc_close,.gpio_read=gpio_read,.gpio_read_analog=gpio_read};
