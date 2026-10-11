#include <micros/application.h>
micros_result_t micros_application_admit(micros_runtime_t *runtime,
    const micros_application_service_t *service, micros_instance_t *instance)
{
    micros_result_t result = micros_runtime_load(runtime, service->image_path,
                                                 service->handles, instance);
    if (result) return result;
    result = micros_runtime_set_policy(runtime, *instance, &service->policy);
    if (result) return result;
    result = micros_runtime_set_config(runtime, *instance, service->configuration,
                                       service->configuration_bytes);
    if (result || !service->verify_memory) return result;
    micros_service_status_t status = {0};
    result = micros_runtime_status(runtime, *instance, &status);
    if (result) return result;
    return status.arena_bytes == service->arena_bytes &&
           status.arena_alignment == service->arena_alignment &&
           status.stack_bytes == service->stack_bytes ? MICROS_OK : MICROS_ERROR_INVALID_ARGUMENT;
}
micros_result_t micros_application_start(micros_runtime_t *runtime,
    const micros_instance_t *instances, const uint32_t *publish_masks,
    size_t count, uint64_t timeout_us)
{
    if (count > MICROS_RUNTIME_SERVICE_CAPACITY) return MICROS_ERROR_CAPACITY;
    for (unsigned pass = 0; pass < 2; ++pass)
        for (size_t i = 0; i < count; ++i) {
            if ((publish_masks[i] != 0) != (pass != 0)) continue;
            micros_result_t result = micros_runtime_start(runtime, instances[i]);
            if (!result) result = micros_runtime_wait_running(runtime, instances[i],
                                                                   2 * timeout_us + UINT64_C(100000));
            if (result) return result;
        }
    return MICROS_OK;
}
int micros_application_healthy(micros_runtime_t *runtime,
    const micros_instance_t *instances, size_t count)
{
    if (!runtime || !count || count > MICROS_RUNTIME_SERVICE_CAPACITY) return 0;
    for (size_t i = 0; i < count; ++i) {
        micros_service_status_t status = {0};
        if (micros_runtime_status(runtime, instances[i], &status) ||
            status.state != MICROS_STATE_RUNNING || status.reboot_required) return 0;
    }
    return 1;
}
micros_result_t micros_application_close(micros_runtime_t **runtime,
    micros_instance_t *instances, size_t count)
{
    if (count > MICROS_RUNTIME_SERVICE_CAPACITY) return MICROS_ERROR_CAPACITY;
    if (!*runtime) return MICROS_OK;
    if (micros_runtime_usage(*runtime).reboot_required) return MICROS_ERROR_REBOOT_REQUIRED;
    for (size_t i = 0; i < count; ++i) {
        if (!instances[i]) continue;
        micros_result_t result = micros_runtime_stop(*runtime, instances[i]);
        if (result == MICROS_ERROR_REBOOT_REQUIRED) return result;
        /* A cooperatively failed hook can still be quiescent and unloadable. */
        result = micros_runtime_unload(*runtime, instances[i]);
        if (result) return result;
        instances[i] = 0;
    }
    micros_result_t result = micros_runtime_destroy(*runtime);
    if (!result) *runtime = NULL;
    return result;
}
