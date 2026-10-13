#include <micros/service.h>
#include <stddef.h>

#ifndef MICROS_SERVICE_TARGET
#define MICROS_SERVICE_TARGET MICROS_BUILD_TARGET
#endif

/* Timer API durations are microseconds: one million microseconds is one second. */
#define HELLO_INTERVAL_US UINT64_C(1000000)

/** @brief Per-instance repeating timer, released when the service stops. */
typedef struct {
    micros_handle_t timer;
} hello_state_t;

/** @brief Write one line to the base-owned serial diagnostic output. */
static micros_result_t print_hello(const micros_service_args_t *service_args,
                                   micros_handle_t timer, void *user_data)
{
    (void)timer;
    (void)user_data;
    static const uint8_t message[] = "Hello world\n";
    return service_args->api->debug_write(service_args->context, message, sizeof(message) - 1);
}

static micros_result_t initialize(const micros_service_args_t *service_args)
{
    (void)service_args;
    return MICROS_OK;
}

static micros_result_t start(const micros_service_args_t *service_args)
{
    hello_state_t *state = service_args->arena;
    return service_args->api->timer_open(service_args->context, HELLO_INTERVAL_US,
                                        HELLO_INTERVAL_US, print_hello, NULL, &state->timer);
}

static micros_result_t step(const micros_service_args_t *service_args)
{
    (void)service_args;
    return MICROS_OK;
}

static micros_result_t stop(const micros_service_args_t *service_args)
{
    hello_state_t *state = service_args->arena;
    return state->timer ? service_args->api->timer_close(service_args->context, state->timer)
                        : MICROS_OK;
}

/** @brief Minimal periodic serial greeting through the native lifecycle interface. */
const micros_service_descriptor_t micros_descriptor = {
    .struct_bytes = sizeof(micros_service_descriptor_t),
    .abi_major = MICROS_ABI_MAJOR,
    .abi_revision = MICROS_ABI_REVISION,
    .target = MICROS_SERVICE_TARGET,
    .arena_bytes = sizeof(hello_state_t),
    .arena_alignment = _Alignof(hello_state_t),
    .stack_bytes = 4096,  /* The runtime's minimum worker stack in bytes. */
    .reserved = 0,
    .init = initialize,
    .start = start,
    .step = step,
    .stop = stop,
};

/* Host loaders discover this entry point; ESP32 reads the descriptor directly. */
const micros_service_descriptor_t *micros_service_query(void)
{
    return &micros_descriptor;
}
