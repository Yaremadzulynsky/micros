/* Exercise the production board command with simulated storage and lifecycle. */
#include <assert.h>
#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include "runtime.h"
#include <micros/transport.h>
#define FILE_PATH_BYTES 64
#define MICROS_GRAPH_CONFIG_BYTES 256
/* The command uses only these graph fields; layout is covered by graph tests. */
typedef struct { unsigned slot, handles, timers, gpio_mask, publish_mask, subscribe_mask; } micros_graph_service_t;
typedef struct { unsigned bytes; uint8_t data[256]; } micros_graph_config_t;
typedef struct { unsigned service_count; micros_graph_service_t services[4]; micros_graph_config_t configurations[4]; } micros_device_graph_t;
typedef struct { unsigned pending, good, sequence; uint8_t good_hash[32]; } micros_activation_record_t;
static micros_runtime_t *runtime = (micros_runtime_t *)(uintptr_t)1;
static micros_instance_t instances[4] = {11, 22};
static unsigned instance_count = 2;
static int running_bank, physical_recovery;
static uint64_t service_boot = 99;
static char deployment_session[33];
static micros_activation_record_t selection = {.good=0, .sequence=7};
static unsigned restarts, polls;
static micros_result_t restart_result;
static micros_service_state_t next_state = MICROS_STATE_RUNNING;
static int graph_ok = 1;
static micros_activation_record_t micros_storage_selection(void) { return selection; }
static int micros_ipc_hex(char c) {
    if (c >= '0' && c <= '9') return c-'0';
    if (c >= 'a' && c <= 'f') return c-'a'+10;
    return -1;
}
static int load_graph(unsigned bank, micros_device_graph_t *graph) {
    assert(bank == 0); memset(graph, 0, sizeof(*graph));
    graph->service_count=2; graph->services[0].handles=2;
    return graph_ok;
}
static void image_path(char *path, unsigned bank, unsigned slot) {
    snprintf(path, FILE_PATH_BYTES, "%u/%u", bank, slot);
}
micros_result_t micros_runtime_restart(micros_runtime_t *r, micros_instance_t *instance,
    const char *path, uint32_t handles, const micros_resource_policy_t *policy,
    const uint8_t *config, uint32_t bytes) {
    (void)policy; (void)config; (void)bytes;
    assert(r == runtime && instance == &instances[0] && handles == 2 && !strcmp(path,"0/0"));
    restarts++; *instance=33; return restart_result;
}
micros_runtime_config_t micros_runtime_default_config(void) {
    return (micros_runtime_config_t){.lifecycle_timeout_us=10};
}
uint64_t micros_platform_now_us(void) { return polls++; }
micros_result_t micros_runtime_status(micros_runtime_t *r, micros_instance_t instance, micros_service_status_t *status) {
    assert(r == runtime && instance == 33);
    status->state=next_state; status->result=0; return 0;
}
static void micros_controller_yield(void) {}
#include "../../src/firmware/controller/protocol/restart.inc"
static const char *valid = "SERVICE RESTART 0 7 0000000000000000000000000000000000000000000000000000000000000000 11 99";
static void reject(const char *command) {
    char response[4096];
    micros_management_request_t request={.response=response,.response_capacity=sizeof(response)};
    unsigned before=restarts;
    service_restart_command(&request,command);
    assert(request.result && restarts==before && instances[1]==22);
}
int main(void) {
    reject("SERVICE RESTART 0");
    reject("SERVICE RESTART 9 7 0000000000000000000000000000000000000000000000000000000000000000 11 99");
    service_boot=100; reject(valid); service_boot=99;
    selection.pending=1; reject(valid); selection.pending=0;
    selection.sequence=8; reject(valid); selection.sequence=7;
    selection.good_hash[0]=1; reject(valid); selection.good_hash[0]=0;
    physical_recovery=1; reject(valid); physical_recovery=0;
    deployment_session[0]='a'; reject(valid); deployment_session[0]=0;
    running_bank=1; reject(valid); running_bank=0;
    graph_ok=0; reject(valid); graph_ok=1;
    char response[4096];
    micros_management_request_t request={.response=response,.response_capacity=sizeof(response)};
    service_restart_command(&request,valid);
    assert(!request.result && restarts==1 && instances[0]==33 && instances[1]==22);
    reject(valid); /* stale instance: don't restart the newly started service again */
    instances[0]=11; next_state=MICROS_STATE_FAILED;
    service_restart_command(&request,valid);
    assert(request.result && restarts==2 && instances[1]==22);
    instances[0]=11; next_state=MICROS_STATE_STARTING;
    service_restart_command(&request,valid);
    assert(request.result && polls<100 && restarts==3 && instances[1]==22);
    instances[0]=11; restart_result=MICROS_ERROR_REBOOT_REQUIRED;
    service_restart_command(&request,valid);
    assert(request.result==MICROS_ERROR_REBOOT_REQUIRED && instances[1]==22);
    /* Both fencing values can exceed 32 bits; never truncate or wrap them. */
    service_boot=UINT64_MAX; instances[0]=UINT64_C(4294967296);
    restart_result=0; next_state=MICROS_STATE_RUNNING;
    const char *wide="SERVICE RESTART 0 7 0000000000000000000000000000000000000000000000000000000000000000 4294967296 18446744073709551615";
    reject("SERVICE RESTART 0 7 0000000000000000000000000000000000000000000000000000000000000000 4294967296 18446744073709551616");
    service_restart_command(&request,wide);
    assert(!request.result && instances[0]==33 && instances[1]==22);
    puts("PASS board restart fencing, one-service scope, failure and bounded startup");
}
