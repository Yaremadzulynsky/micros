#ifndef MICROS_COORDINATION_SERVICE_H
#define MICROS_COORDINATION_SERVICE_H

#include <micros/service.h>
#include <micros/coordination.h>

/* Copy this opaque invocation token when hardware completion is asynchronous. */
typedef struct {
    micros_handle_t _port;
    micros_coord_info_t _identity;
} micros_action_t;

typedef struct {
    micros_service_hook_t init;
    micros_service_hook_t start;
    micros_service_hook_t step;
    micros_service_hook_t stop;
} micros_service_hooks_t;

/* Application state stays first: existing hooks and timers see their usual arena.
 * Adapter storage is instance-owned and included in admission's memory budget. */
#define MICROS_COORDINATION_SERVICE(name, state_type, stack_size, hooks, callbacks) \
    typedef struct { \
        state_type application; \
        name##_coordination_t coordination; \
    } name##_service_storage_t; \
    name##_coordination_t *name##_coordination_context(const micros_service_args_t *args) \
    { return &((name##_service_storage_t *)args->arena)->coordination; } \
    static micros_result_t name##_managed_init(const micros_service_args_t *args) \
    { \
        micros_result_t status = name##_coordination_open(args, &(callbacks)); \
        if (status) return status; \
        return (hooks).init ? (hooks).init(args) : MICROS_OK; \
    } \
    static micros_result_t name##_managed_start(const micros_service_args_t *args) \
    { return (hooks).start ? (hooks).start(args) : MICROS_OK; } \
    static micros_result_t name##_managed_step(const micros_service_args_t *args) \
    { \
        micros_result_t status = name##_coordination_dispatch(args, &(callbacks)); \
        if (status) return status; \
        return (hooks).step ? (hooks).step(args) : MICROS_OK; \
    } \
    static micros_result_t name##_managed_stop(const micros_service_args_t *args) \
    { \
        micros_result_t status = (hooks).stop ? (hooks).stop(args) : MICROS_OK; \
        micros_result_t cleanup = name##_coordination_close(args); \
        return status ? status : cleanup; \
    } \
    const micros_service_descriptor_t micros_descriptor = { \
        .struct_bytes = sizeof(micros_service_descriptor_t), \
        .abi_major = MICROS_ABI_MAJOR, .abi_revision = MICROS_ABI_REVISION, \
        .target = MICROS_BUILD_TARGET, \
        .arena_bytes = sizeof(name##_service_storage_t), \
        .arena_alignment = _Alignof(name##_service_storage_t), \
        .stack_bytes = (stack_size), \
        .init = name##_managed_init, .start = name##_managed_start, \
        .step = name##_managed_step, .stop = name##_managed_stop, \
    }; \
    const micros_service_descriptor_t *micros_service_query(void) \
    { return &micros_descriptor; }

#endif
