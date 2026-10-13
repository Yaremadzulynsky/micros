#ifndef MICROS_APPLICATION_H
#define MICROS_APPLICATION_H
#include "runtime.h"
#ifdef __cplusplus
extern "C" {
#endif
/* Logical launch inputs, independent of transport, flash layout and wire format.
 * Paths/configuration are borrowed only for the duration of admission. */
typedef struct {
    const char *image_path;
    uint32_t handles;
    micros_resource_policy_t policy;
    const uint8_t *configuration;
    uint32_t configuration_bytes;
    int verify_memory;
    uint32_t arena_bytes, arena_alignment, stack_bytes;
} micros_application_service_t;
/* Failure preserves any admitted instance so the controller can safely close it. */
micros_result_t micros_application_admit(micros_runtime_t *runtime,
    const micros_application_service_t *service, micros_instance_t *instance);
/* Admit ALL services before calling this. Subscribers start before publishers;
 * each must reach Running before its dependents start. timeout_us is the budget
 * for EACH lifecycle hook; startup allows init + start plus scheduling margin.
 * No hooks run on admission. */
micros_result_t micros_application_start(micros_runtime_t *runtime,
    const micros_instance_t *instances, const uint32_t *publish_masks,
    size_t count, uint64_t timeout_us);
int micros_application_healthy(micros_runtime_t *runtime,
    const micros_instance_t *instances, size_t count);
/* Never unload live native code. On failure retain the runtime for recovery. */
micros_result_t micros_application_close(micros_runtime_t **runtime,
    micros_instance_t *instances, size_t count);
#ifdef __cplusplus
}
#endif
#endif
