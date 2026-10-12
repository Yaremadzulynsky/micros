#ifndef MICROS_SERVICE_RESTART_COMMAND_H
#define MICROS_SERVICE_RESTART_COMMAND_H
#include <stdlib.h>
#include "../../kernel/support/integer.h"
/* Controller-only command, included after the board's graph/storage helpers.
 * No new service hooks or channel teardown. Transport serializes all mutations. */
static __attribute__((noinline)) void service_restart_command(micros_management_request_t *request, const char *command)
{
    unsigned index = 0, sequence = 0;
    uint64_t expected_instance = 0, expected_boot = 0;
    char expected[65] = {0}; const char *fields = command;
    micros_activation_record_t selected = micros_storage_selection();
    int valid = micros_parse_prefix(&fields, "SERVICE RESTART ") &&
        micros_parse_unsigned(&fields, &index) && micros_parse_unsigned(&fields, &sequence) &&
        micros_parse_word(&fields, expected, sizeof(expected)) &&
        micros_parse_u64(&fields, 10, &expected_instance) && micros_parse_u64(&fields, 10, &expected_boot) &&
        micros_parse_end(fields) && expected_boot == service_boot && strlen(expected) == 64 && runtime &&
        index < instance_count && !selected.pending && selected.good < 2 &&
        running_bank == (int)selected.good && selected.sequence == sequence &&
        instances[index] == expected_instance && !physical_recovery && !deployment_session[0];
    for (unsigned i = 0; valid && i < 32; ++i) {
        int hi = micros_ipc_hex(expected[i*2]), lo = micros_ipc_hex(expected[i*2+1]);
        if (hi < 0 || lo < 0 || (unsigned)((hi<<4)|lo) != selected.good_hash[i]) valid = 0;
    }
    micros_device_graph_t *graph=valid?malloc(sizeof(*graph)):NULL;
    if (!graph) valid=0;
    if (valid) valid = load_graph(selected.good, graph) && index < graph->service_count;
    micros_result_t result = MICROS_ERROR_STATE;
    if (valid) {
        micros_graph_service_t *service = &graph->services[index];
        micros_resource_policy_t policy = {service->timers, service->gpio_mask,
                                           service->publish_mask, service->subscribe_mask};
        char path[FILE_PATH_BYTES];
        image_path(path, selected.good, service->slot);
        result = micros_runtime_restart(runtime, &instances[index], path, service->handles,
            &policy, graph->configurations[index].data, graph->configurations[index].bytes);
        /* Wait only for this service. A normal lifecycle failure never
         * tears down peers or rolls back the confirmed application. */
        uint64_t deadline = micros_platform_now_us() + 2 * micros_runtime_default_config().lifecycle_timeout_us;
        while (!result) {
            micros_service_status_t status = {0};
            result = micros_runtime_status(runtime, instances[index], &status);
            if (result || status.state == MICROS_STATE_RUNNING) break;
            if (status.state == MICROS_STATE_FAILED || micros_platform_now_us() >= deadline) {
                result = status.result ? status.result : MICROS_ERROR_STATE;
                break;
            }
            micros_controller_yield();
        }
    }
    free(graph);
    request->result = result;
    snprintf(request->response, request->response_capacity,
             "{\"service_index\":%u,\"result\":%d}", index, (int)result);
    return;
}
#endif
