#include "runtime.h"
#include <inttypes.h>
#include <micros/platform.h>
#include <stdio.h>
#include <stdlib.h>

/* Ten samples at the example's 5 ms period keep the local demonstration short.
 * Poll every millisecond to observe state/deadline changes without busy waiting.
 * Exit 2 retains the M1 convention for whole-process recovery after timeout. */
#define DEMO_RUN_US UINT64_C(50000)
#define STATUS_POLL_US UINT64_C(1000)
#define EXIT_REBOOT_REQUIRED 2

int main(int argc, char **argv)
{
    if (argc != 2) {
        fprintf(stderr, "usage: micros-runtime SERVICE.mimg\n");
        return EXIT_FAILURE;
    }
    micros_runtime_config_t config = micros_runtime_default_config();
    micros_runtime_t *runtime = micros_runtime_create(&config);
    if (!runtime)
        return EXIT_FAILURE;
    micros_instance_t instance;
    micros_result_t result =
        micros_runtime_load(runtime, argv[1], MICROS_RUNTIME_HANDLES_PER_SERVICE, &instance);
    if (result) {
        fprintf(stderr, "REJECT admission result=%d\n", result);
        micros_runtime_destroy(runtime);
        return EXIT_FAILURE;
    }
    micros_runtime_usage_t usage = micros_runtime_usage(runtime);
    printf("Loaded image=%zu arena=%zu stack_requested=%zu stack_host=%zu handles_reserved=%u\n",
           usage.image_bytes, usage.arena_bytes, usage.stack_bytes, usage.platform_stack_bytes,
           usage.reserved_handles);
    printf("Kernel metadata=%zu supervisor_stack=%zu arena_storage=%zu\n",
           usage.kernel_metadata_bytes, usage.supervisor_stack_bytes, usage.arena_storage_bytes);
    result = micros_runtime_start(runtime, instance);
    micros_platform_sync_t *poll = micros_platform_sync_create();
    if (!poll)
        exit(EXIT_FAILURE);
    uint64_t finish_us = micros_platform_now_us() + DEMO_RUN_US;
    micros_service_status_t status;
    while (!result && micros_platform_now_us() < finish_us) {
        micros_runtime_status(runtime, instance, &status);
        if (status.reboot_required)
            break;
        if (status.state == MICROS_STATE_FAILED || status.state == MICROS_STATE_STOPPED)
            break;
        micros_platform_lock(poll);
        micros_platform_wait(poll, micros_platform_now_us() + STATUS_POLL_US);
        micros_platform_unlock(poll);
    }
    if (!result)
        result = micros_runtime_stop(runtime, instance);
    micros_runtime_status(runtime, instance, &status);
    printf("%s result=%d steps=%" PRIu64 " callbacks=%" PRIu64 " handles=%u reboot_required=%u\n",
           micros_runtime_state_name(status.state), result, status.completed_steps,
           status.completed_callbacks, status.owned_handles, status.reboot_required);
    if (status.reboot_required) {
        fprintf(stderr, "FATAL service deadline; process recovery required; resources retained\n");
        fflush(NULL);
        _Exit(EXIT_REBOOT_REQUIRED);
    }
    micros_runtime_unload(runtime, instance);
    usage = micros_runtime_usage(runtime);
    printf("Unloaded services=%u handles=%u tasks=%u image=%zu arena=%zu stacks=%zu\n",
           usage.loaded_services, usage.live_handles, usage.live_tasks, usage.image_bytes,
           usage.arena_bytes, usage.platform_stack_bytes);
    micros_platform_sync_destroy(poll);
    micros_runtime_destroy(runtime);
    return result ? EXIT_FAILURE : EXIT_SUCCESS;
}
