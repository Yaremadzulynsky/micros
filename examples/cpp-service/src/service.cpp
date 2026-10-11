#include <micros/service.h>

#ifndef MICROS_SERVICE_TARGET
#define MICROS_SERVICE_TARGET MICROS_BUILD_TARGET
#endif

/* Each hook returns a result to the runtime. Add service behavior here. */
static micros_result_t initialize(const micros_service_args_t *service_args)
{
    (void)service_args;
    return MICROS_OK;
}

static micros_result_t start(const micros_service_args_t *service_args)
{
    (void)service_args;
    return MICROS_OK;
}

static micros_result_t step(const micros_service_args_t *service_args)
{
    (void)service_args;
    return MICROS_OK;
}

static micros_result_t stop(const micros_service_args_t *service_args)
{
    (void)service_args;
    return MICROS_OK;
}

/** @brief Stateless C++ service implementing the native C ABI lifecycle. */
extern "C" const micros_service_descriptor_t micros_descriptor = {
    sizeof(micros_service_descriptor_t),
    MICROS_ABI_MAJOR,
    MICROS_ABI_REVISION,
    MICROS_SERVICE_TARGET,
    0,    // No per-instance state needs an arena.
    1,    // Byte alignment suffices for an unused arena.
    4096, // The runtime's minimum worker stack in bytes.
    0,    // Reserved ABI word must be zero.
    initialize,
    start,
    step,
    stop,
};

/* C linkage lets the loader discover this entry point by name. */
extern "C" const micros_service_descriptor_t *micros_service_query(void)
{
    return &micros_descriptor;
}
