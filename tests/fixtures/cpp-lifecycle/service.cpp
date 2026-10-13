#include <micros/service.h>
#include <new>

#ifndef MICROS_SERVICE_TARGET
#define MICROS_SERVICE_TARGET MICROS_BUILD_TARGET
#endif

/** Per-instance C++ state lives entirely inside the kernel-provided arena. */
struct ServiceState {
    unsigned completed_steps;
};

static micros_result_t initialize(const micros_service_args_t *args)
{
    // Placement construction starts the C++ object lifetime without allocating memory.
    new (args->arena) ServiceState{};
    constexpr char message[] = "C++ service initialized through the C ABI\n";
    return args->api->debug_write(args->context, reinterpret_cast<const uint8_t *>(message),
                                  sizeof(message) - 1);
}
static micros_result_t start(const micros_service_args_t *)
{
    return MICROS_OK;
}
static micros_result_t step(const micros_service_args_t *args)
{
    auto *state = static_cast<ServiceState *>(args->arena);
    ++state->completed_steps;
    return MICROS_OK;
}
static micros_result_t stop(const micros_service_args_t *args)
{
    auto *state = static_cast<ServiceState *>(args->arena);
    state->~ServiceState();
    constexpr char message[] = "C++ service stopped through the C ABI\n";
    return args->api->debug_write(args->context, reinterpret_cast<const uint8_t *>(message),
                                  sizeof(message) - 1);
}
/** Constant descriptor has no dynamic initialization, RTTI, exceptions or hidden task state. */
extern "C" const micros_service_descriptor_t micros_descriptor = {
    sizeof(micros_service_descriptor_t),
    MICROS_ABI_MAJOR,
    MICROS_ABI_REVISION,
    MICROS_SERVICE_TARGET,
    sizeof(ServiceState),
    alignof(ServiceState),
    4096, // The shared native profile's minimum worker stack; hardware verifies remaining headroom.
    0,    // Reserved ABI word must be zero.
    initialize,
    start,
    step,
    stop};
extern "C" const micros_service_descriptor_t *micros_service_query(void)
{
    return &micros_descriptor;
}
