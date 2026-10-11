#include <micros/update.h>
#include "esp_ota_ops.h"
#include "esp_app_desc.h"
#include "esp_timer.h"
#include "nvs.h"
#include "mbedtls/sha256.h"
#include <assert.h>
#include <setjmp.h>
#include <stdlib.h>
#include <string.h>
static esp_partition_t partitions[]={{16,0x180000},{17,0x180000}};
static unsigned running, boot, written, aborted, valid, state, timer_live;
static int fail_write, fail_end, fail_select;
static void (*timeout_callback)(void *);
static jmp_buf reset;
static esp_app_desc_t desc={{1}};
static uint8_t owner[2][64];
static uint8_t graph_hash[32];
static int owner_exists[2];
const esp_partition_t *esp_ota_get_running_partition(void) { return &partitions[running]; }
const esp_partition_t *esp_ota_get_next_update_partition(const esp_partition_t *p) { (void)p;return &partitions[1-running]; }
int esp_ota_get_state_partition(const esp_partition_t *p,esp_ota_img_states_t *s) { (void)p;*s=state;return 0; }
int esp_ota_begin(const esp_partition_t *p,size_t n,esp_ota_handle_t *h) {
    assert(p==&partitions[1-running] && n==OTA_WITH_SEQUENTIAL_WRITES); *h=1;written=0;return 0;
}
int esp_ota_write(esp_ota_handle_t h,const void *d,size_t n) { assert(h==1 && d);if(fail_write)return -1;written+=n;return 0; }
int esp_ota_end(esp_ota_handle_t h) { assert(h==1);return fail_end ? -1:0; }
int esp_ota_abort(esp_ota_handle_t h) { assert(h==1);aborted++;return 0; }
int esp_ota_set_boot_partition(const esp_partition_t *p) { if(fail_select)return -1;boot=(unsigned)(p-partitions);return 0; }
int esp_ota_mark_app_valid_cancel_rollback(void) { valid++;return 0; }
int esp_timer_create(const esp_timer_create_args_t *a,esp_timer_handle_t *t) { timeout_callback=a->callback;*t=&timer_live;return 0; }
int esp_timer_start_once(esp_timer_handle_t t,uint64_t us) { assert(t && us==180000000);timer_live=1;return 0; }
int esp_timer_stop(esp_timer_handle_t t) { assert(t);timer_live=0;return 0; }
int esp_timer_delete(esp_timer_handle_t t) { assert(t);return 0; }
void esp_restart(void) { longjmp(reset,1); }
const esp_app_desc_t *esp_app_get_description(void) { return &desc; }
int nvs_open(const char *ns,int mode,nvs_handle_t *h) { assert(!strcmp(ns,"micros_base"));*h=1;return mode==NVS_READONLY && !owner_exists[0] && !owner_exists[1] ? -1:0; }
int nvs_get_blob(nvs_handle_t h,const char *k,void *v,size_t *n) { unsigned bank=!strcmp(k,"owner1");assert(h && *n==64);if(!owner_exists[bank])return -1;memcpy(v,owner[bank],64);return 0; }
int nvs_set_blob(nvs_handle_t h,const char *k,const void *v,size_t n) { unsigned bank=!strcmp(k,"owner1");assert(h && n==64);memcpy(owner[bank],v,64);owner_exists[bank]=1;return 0; }
int nvs_commit(nvs_handle_t h) { assert(h);return 0; }
void nvs_close(nvs_handle_t h) { assert(h); }
void mbedtls_sha256_init(mbedtls_sha256_context *c) { c->sum=0; }
void mbedtls_sha256_free(mbedtls_sha256_context *c) { (void)c; }
int mbedtls_sha256_starts(mbedtls_sha256_context *c,int n) { (void)n;c->sum=0;return 0; }
int mbedtls_sha256_update(mbedtls_sha256_context *c,const void *p,size_t n) { const uint8_t *b=p;while(n--)c->sum+=*b++;return 0; }
int mbedtls_sha256_finish(mbedtls_sha256_context *c,uint8_t *p) { memset(p,c->sum,32);return 0; }
int main(int argc,char **argv)
{
    assert(argc==2);
    uint8_t header[40]={0}, data[4096]={0}; uint32_t bytes=5000;
    memcpy(header,"MBO1",4);memcpy(header+4,&bytes,4);
    if(!strcmp(argv[1],"trial")) {
        assert(!micros_base_application_allowed(graph_hash));assert(micros_base_bind_application(0, graph_hash));
        assert(micros_base_application_allowed(graph_hash));
        graph_hash[0]=1;assert(!micros_base_application_allowed(graph_hash));
        assert(micros_base_bind_application(1,graph_hash));
        assert(micros_base_application_allowed(graph_hash));graph_hash[0]=0;
        assert(micros_base_application_allowed(graph_hash)); /* Each staging bank keeps its binding. */
        desc.app_elf_sha256[0]=2;assert(!micros_base_application_allowed(graph_hash));
        state=1;micros_base_boot();assert(micros_base_pending() && timer_live);
        assert(!micros_base_begin(header,40));assert(!micros_base_bind_application(0, graph_hash));
        if(!setjmp(reset)) { timeout_callback(NULL);assert(0); }
        assert(micros_base_confirm() && valid==1 && !timer_live);
        assert(micros_base_confirm() && valid==1);
        assert(!micros_base_application_allowed(graph_hash)); /* Confirm never rewrites app ownership. */
        desc.app_elf_sha256[0]=1;assert(micros_base_application_allowed(graph_hash));
        return 0;
    }
    if(!strcmp(argv[1],"slot1")) { running=boot=1; }
    micros_base_boot();
    assert(!micros_base_begin(header,39));header[0]='x';assert(!micros_base_begin(header,40));header[0]='M';
    uint32_t large=0x180001;memcpy(header+4,&large,4);assert(!micros_base_begin(header,40));memcpy(header+4,&bytes,4);
    assert(micros_base_begin(header,40));assert(!micros_base_begin(header,40));
    assert(!micros_base_chunk(1,data,4096));assert(!micros_base_chunk(0,data,4097));assert(!micros_base_chunk(0,data,0));
    if(!strcmp(argv[1],"write_fail")) {
        fail_write=1;assert(!micros_base_chunk(0,data,4096));assert(!micros_base_busy() && aborted==1 && boot==running);return 0;
    }
    assert(micros_base_chunk(0,data,4096));assert(!micros_base_chunk(0,data,4096));
    assert(!micros_base_finish());assert(!micros_base_chunk(4096,data,905));
    if(!strcmp(argv[1],"digest_fail")) data[0]=1;
    assert(micros_base_chunk(4096,data,904));
    fail_end=!strcmp(argv[1],"end_fail");fail_select=!strcmp(argv[1],"select_fail");
    int okay=micros_base_finish();
    if(fail_end || fail_select || !strcmp(argv[1],"digest_fail")) {
        assert(!okay && boot==running && !micros_base_busy());
    } else if(!strcmp(argv[1],"abort")) { /* Sealed selection cannot be undone by session expiry. */
        assert(okay);micros_base_abort();assert(micros_base_busy() && boot==1-running);
    } else {
        assert(okay && boot==1-running && written==5000 && micros_base_busy());
        char status[256];assert(micros_base_status(status,sizeof(status)));assert(!micros_base_status(status,2));
    }
}
