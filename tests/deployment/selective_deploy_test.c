#define micros_controller_reset test_controller_reset
#define micros_board_validate_bytes test_validate_bytes
#define MICROS_CAP_SELECTIVE_UPDATE 1
#define _POSIX_C_SOURCE 200809L
#include "storage.h"
#include "runtime.h"
#include <micros/platform.h>
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#define FILE_PATH_BYTES 4096
#define HEALTH_WINDOW_US 5000000
static micros_runtime_t *runtime;
static micros_instance_t instances[4];
static unsigned instance_count=2;
static int running_bank=0;
static uint64_t health_deadline_us;
static micros_device_graph_t graphs[2];
static micros_activation_record_t record;
static const char *directory;
static int broken[2], fail_switch, fail_journal;
static unsigned switches;
static void vTaskDelay(int ticks) {
    struct timespec duration={0,ticks*1000000}; nanosleep(&duration,NULL);
}
void micros_controller_reset(void) { assert(!"unexpected board reboot"); abort(); }
static void recover_if_needed(void) { assert(!micros_runtime_usage(runtime).reboot_required); }
static void image_path(char *path, unsigned bank, unsigned slot) {
    snprintf(path,FILE_PATH_BYTES,"%s/fixture_%s.mimg",directory,
             slot ? "NORMAL_PEER" : broken[bank] ? "FAIL_INIT" : "NORMAL");
}
static int load_graph(unsigned bank, micros_device_graph_t *graph) { *graph=graphs[bank]; return 1; }
micros_activation_record_t micros_storage_selection(void) { return record; }
static void assert_flash_quiescent(void) {
    micros_service_status_t a,b;
    assert(!micros_runtime_status(runtime,instances[1],&a));
    vTaskDelay(25);
    assert(!micros_runtime_status(runtime,instances[1],&b));
    assert(a.completed_steps==b.completed_steps && a.completed_callbacks==b.completed_callbacks);
}
int micros_storage_select(micros_activation_record_t next) {
    assert_flash_quiescent();
    if (fail_journal) return 0;
    record=next; record.sequence++; return 1;
}
static void clear_trial(micros_activation_record_t *r) { r->pending=0;r->candidate=MICROS_ACTIVATION_NONE;r->attempts=0; }
int micros_deployment_hash(unsigned bank, uint8_t hash[32]) { memset(hash,bank+1,32);return 1; }
static int micros_base_bind_application(unsigned bank, const uint8_t *hash) { (void)bank;(void)hash;assert_flash_quiescent();return 1; }
void micros_storage_fault_boundary(unsigned boundary) { assert(boundary==10); }
uint8_t *micros_storage_read_image(unsigned bank, unsigned slot, size_t *bytes) {
    char path[FILE_PATH_BYTES];image_path(path,bank,slot);FILE *f=fopen(path,"rb");assert(f);
    assert(!fseek(f,0,SEEK_END));*bytes=(size_t)ftell(f);rewind(f);
    uint8_t *data=malloc(*bytes);assert(data && fread(data,1,*bytes,f)==*bytes);fclose(f);return data;
}
int micros_board_validate_bytes(const void *bytes, size_t size, unsigned slot) { (void)bytes;(void)slot;return size<64; }
int micros_storage_rebind_images(unsigned bank) {
    (void)bank;switches++;
    if(fail_switch) { fail_switch=0;return 0; }
    micros_service_status_t a,b;
    assert(!micros_runtime_status(runtime,instances[1],&a));
    vTaskDelay(5);
    assert(!micros_runtime_status(runtime,instances[1],&b));
    assert(a.completed_steps==b.completed_steps && a.completed_callbacks==b.completed_callbacks);
    return 1;
}
#define controller_event printf
#include "../../src/firmware/controller/support/selective.inc"
static micros_service_status_t wait_for(unsigned index, int failed) {
    uint64_t deadline=micros_platform_now_us()+2000000;
    micros_service_status_t status;
    do {
        assert(!micros_runtime_status(runtime,instances[index],&status));
        if(failed ? status.state==MICROS_STATE_FAILED : status.state==MICROS_STATE_RUNNING && status.completed_callbacks>2) return status;
        vTaskDelay(1);
    } while(micros_platform_now_us()<deadline);
    assert(!"lifecycle timeout");return status;
}
int main(int argc,char **argv) {
    assert(argc==2);directory=argv[1];
    micros_runtime_config_t config=micros_runtime_default_config();runtime=micros_runtime_create(&config);assert(runtime);
    record.good=0;
    for(unsigned bank=0;bank<2;bank++) {
        graphs[bank].service_count=2;
        for(unsigned i=0;i<2;i++) graphs[bank].services[i]=(micros_graph_service_t){.slot=i,.handles=2,.timers=1,.gpio_mask=1u<<i};
    }
    for(unsigned i=0;i<2;i++) {
        char path[FILE_PATH_BYTES];image_path(path,0,i);
        assert(!micros_runtime_load(runtime,path,2,&instances[i]));assert(!micros_runtime_start(runtime,instances[i]));wait_for(i,0);
    }
    for (unsigned i=0;i<2;i++) {
        micros_service_status_t status;assert(!micros_runtime_status(runtime,instances[i],&status));
        for(unsigned bank=0;bank<2;bank++) {
            graphs[bank].services[i].arena_bytes=status.arena_bytes;
            graphs[bank].services[i].arena_alignment=status.arena_alignment;
            graphs[bank].services[i].stack_bytes=status.stack_bytes;
        }
    }
    micros_instance_t peer=instances[1], target=instances[0];
    graphs[1].configurations[0].bytes=1;graphs[1].configurations[0].data[0]=9;
    fail_journal=1;assert(selective_begin(1,&graphs[1])==-1);fail_journal=0;
    assert(instances[0]==target && instances[1]==peer && !switches);
    assert(selective_begin(1,&graphs[1])==1 && selective.changed==1);
    wait_for(0,0);micros_service_status_t before=wait_for(1,0);
    assert(instances[0]!=target && instances[1]==peer && record.pending && running_bank==1);
    record.good=1;clear_trial(&record);selective.active=0;health_deadline_us=0;
    /* A bad replacement rolls back only its changed service. */
    broken[0]=1;
    assert(selective_begin(0,&graphs[0])==1 && selective.changed==1);
    wait_for(0,1);
    assert(selective_restore());wait_for(0,0);
    micros_service_status_t after=wait_for(1,0);
    assert(instances[1]==peer && after.completed_steps>before.completed_steps && running_bank==1 && !record.pending);
    broken[0]=0;
    fail_switch=1;
    assert(selective_begin(0,&graphs[0])==1);wait_for(0,0);
    assert(!selective.active && instances[1]==peer && running_bank==1 && !record.pending);
    graphs[0].channel_count=1;
    assert(selective_begin(0,&graphs[0])==0 && instances[1]==peer); /* Explicit shared-layout fallback. */
    for(unsigned i=0;i<2;i++) { assert(!micros_runtime_stop(runtime,instances[i]));assert(!micros_runtime_unload(runtime,instances[i])); }
    assert(!micros_runtime_destroy(runtime));
    puts("PASS selective configuration/code trials, mapping quiescence, failed-start rollback, journal rejection and shared-layout fallback");
}
