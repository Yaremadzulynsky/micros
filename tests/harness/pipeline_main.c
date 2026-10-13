#include "runtime.h"
#include <inttypes.h>
#include <micros/platform.h>
#include <stdio.h>
#include <stdlib.h>
/* The roadmap fixture retains eight 64-byte samples at 10 Hz. Two seconds is
 * long enough for the paused reader to miss data and then resume decoding. */
#define DEMO_DURATION_US UINT64_C(2000000)
#define POLL_US UINT64_C(1000)
#define DEMO_CHANNEL_KEY 1u
#define DEMO_DEPTH 8u
#define DEMO_PAYLOAD_BYTES 64u
#define PATH_BYTES 4096u /* Bounded local image path, checked before use. */
int main(int argc, char **argv)
{
    if (argc != 2) {
        fprintf(stderr, "usage: micros-pipeline BUILD_DIRECTORY\n");
        return EXIT_FAILURE;
    }
    micros_runtime_config_t config = micros_runtime_default_config();
    micros_runtime_t *runtime = micros_runtime_create(&config);
    if (!runtime)
        return EXIT_FAILURE;
    if (micros_runtime_channel_create(runtime, DEMO_CHANNEL_KEY, MICROS_CHANNEL_STREAM, DEMO_DEPTH,
                                      DEMO_PAYLOAD_BYTES))
        return EXIT_FAILURE;
    const char *names[] = {"fast", "slow", "publisher"};
    micros_instance_t instances[3]; /* Two subscribers and one independent publisher. */
    for (unsigned participant = 0; participant < 3; ++participant) {
        char path[PATH_BYTES];
        int size = snprintf(path, sizeof(path), "%s/pipeline_%s.mimg", argv[1], names[participant]);
        if (size < 0 || (size_t)size >= sizeof(path))
            return EXIT_FAILURE;
        if (micros_runtime_load(runtime, path, 2, &instances[participant]))
            return EXIT_FAILURE;
    }
    micros_platform_sync_t *pause = micros_platform_sync_create();
    if (!pause)
        return EXIT_FAILURE;
    /* Admit every image before any execution; subscribe before publishing. */
    for (unsigned participant = 0; participant < 3; ++participant) {
        if (micros_runtime_start(runtime, instances[participant]))
            return EXIT_FAILURE;
        uint64_t deadline = micros_platform_now_us() + config.lifecycle_timeout_us;
        micros_service_status_t status;
        do {
            micros_runtime_status(runtime, instances[participant], &status);
            if (status.state == MICROS_STATE_RUNNING)
                break;
            if (status.state == MICROS_STATE_FAILED || micros_platform_now_us() >= deadline)
                return EXIT_FAILURE;
            micros_platform_lock(pause);
            micros_platform_wait(pause, micros_platform_now_us() + POLL_US);
            micros_platform_unlock(pause);
        } while (1);
    }
    uint64_t end_us = micros_platform_now_us() + DEMO_DURATION_US;
    while (micros_platform_now_us() < end_us) {
        micros_runtime_usage_t usage = micros_runtime_usage(runtime);
        if (usage.reboot_required) {
            fprintf(stderr, "FATAL runtime recovery required\n");
            fflush(NULL);
            _Exit(2);
        }
        micros_platform_lock(pause);
        micros_platform_wait(pause, micros_platform_now_us() + POLL_US);
        micros_platform_unlock(pause);
    }
    for (unsigned participant = 0; participant < 3; ++participant) {
        if (micros_runtime_stop(runtime, instances[participant]))
            return EXIT_FAILURE;
        micros_service_status_t status;
        micros_runtime_status(runtime, instances[participant], &status);
        printf("%s: %s callbacks=%" PRIu64 " diagnostics=%u\n", names[participant],
               micros_runtime_state_name(status.state), status.completed_callbacks,
               status.diagnostic_writes);
        if (micros_runtime_unload(runtime, instances[participant]))
            return EXIT_FAILURE;
    }
    micros_runtime_channel_destroy(runtime, DEMO_CHANNEL_KEY);
    micros_runtime_usage_t usage = micros_runtime_usage(runtime);
    printf("BASELINE services=%u handles=%u channels=%u channel_bytes=%zu tasks=%u\n",
           usage.loaded_services, usage.live_handles, usage.channels, usage.channel_bytes,
           usage.live_tasks);
    micros_platform_sync_destroy(pause);
    return micros_runtime_destroy(runtime) ? EXIT_FAILURE : EXIT_SUCCESS;
}
