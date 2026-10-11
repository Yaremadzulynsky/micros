#include <micros/application.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
int main(int argc, char **argv)
{
    assert(argc == 2);
    char path[4096];
    snprintf(path, sizeof(path), "%s/fixture_NORMAL.mimg", argv[1]);
    micros_runtime_config_t config = micros_runtime_default_config();
    config.lifecycle_timeout_us = 500000;
    micros_runtime_t *runtime = micros_runtime_create(&config);
    micros_instance_t instance = 0;
    micros_application_service_t input = {.image_path = path, .handles = 8,
        .policy = {.timer_limit = 8, .gpio_mask = 1}};
    assert(!micros_application_admit(runtime, &input, &instance));
    micros_service_status_t status;
    assert(!micros_runtime_status(runtime, instance, &status));
    assert(status.state == MICROS_STATE_LOADED && !status.completed_steps);
    uint32_t publishes = 0;
    assert(!micros_application_healthy(runtime, &instance, 1));
    assert(!micros_application_start(runtime, &instance, &publishes, 1, 500000));
    assert(micros_application_healthy(runtime, &instance, 1));
    assert(!micros_application_close(&runtime, &instance, 1));
    assert(!runtime && !instance);
    /* Failed admission retains the loaded instance for safe cleanup. */
    runtime = micros_runtime_create(&config);
    input.verify_memory = 1; input.arena_bytes = 999999;
    assert(micros_application_admit(runtime, &input, &instance));
    assert(instance && !micros_application_healthy(runtime, &instance, 1));
    assert(!micros_application_close(&runtime, &instance, 1));
    /* A cooperative init failure must propagate and remain reclaimable. */
    snprintf(path, sizeof(path), "%s/fixture_FAIL_INIT.mimg", argv[1]);
    input.verify_memory = 0;
    runtime = micros_runtime_create(&config);
    assert(!micros_application_admit(runtime, &input, &instance));
    assert(micros_application_start(runtime, &instance, &publishes, 1, 500000));
    assert(!micros_application_healthy(runtime, &instance, 1));
    assert(!micros_application_close(&runtime, &instance, 1));
    assert(!runtime && !instance);
    /* Both hooks may legally consume more than one hook budget in total. */
    snprintf(path, sizeof(path), "%s/fixture_SLOW_BOTH.mimg", argv[1]);
    config.lifecycle_timeout_us = 300000;
    runtime = micros_runtime_create(&config);
    assert(!micros_application_admit(runtime, &input, &instance));
    assert(!micros_application_start(runtime, &instance, &publishes, 1, config.lifecycle_timeout_us));
    assert(micros_application_healthy(runtime, &instance, 1));
    assert(!micros_application_close(&runtime, &instance, 1));
    puts("shared application lifecycle passed");
}
