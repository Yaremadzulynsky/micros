#include <micros/service.h>

/* A 5 ms synthetic sample period is visible in host traces without busy work.
 * Line zero is the first of the host BSP's four simulated digital lines. */
#define SAMPLE_PERIOD_US UINT64_C(5000)
#define SAMPLE_LINE UINT32_C(0)
#define SERVICE_STACK_BYTES UINT32_C(4096) /* Same bounded request as the M1 demo. */

/** @brief Per-load sensor state, owned by the service in its initially zeroed arena. */
typedef struct {
    micros_handle_t timer; /**< Periodic sampling registration, closed during stop. */
    micros_handle_t gpio;  /**< Exclusive simulated input/output line. */
    uint32_t sample_count; /**< Successfully completed timer samples in this run. */
} runtime_service_state_t;

static micros_result_t sample(const micros_service_args_t *args, micros_handle_t timer,
                              void *user_data)
{
    (void)timer;
    runtime_service_state_t *state = user_data;
    uint32_t level;
    micros_result_t result = args->api->gpio_read(args->context, state->gpio, &level);
    if (result)
        return result;
    result = args->api->gpio_write(args->context, state->gpio, !level);
    if (result)
        return result;
    ++state->sample_count;
    static const uint8_t message[] = "runtime timer sampled simulated GPIO\n";
    return args->api->debug_write(args->context, message, sizeof(message) - 1);
}
static micros_result_t initialize(const micros_service_args_t *args)
{
    runtime_service_state_t *state = args->arena;
    return args->api->gpio_open(args->context, SAMPLE_LINE, &state->gpio);
}
static micros_result_t start(const micros_service_args_t *args)
{
    runtime_service_state_t *state = args->arena;
    return args->api->timer_open(args->context, SAMPLE_PERIOD_US, SAMPLE_PERIOD_US, sample, state,
                                 &state->timer);
}
static micros_result_t step(const micros_service_args_t *args)
{
    (void)args;
    return MICROS_OK;
}
static micros_result_t stop(const micros_service_args_t *args)
{
    runtime_service_state_t *state = args->arena;
    micros_result_t result = MICROS_OK;
    if (state->timer)
        result = args->api->timer_close(args->context, state->timer);
    if (state->gpio) {
        micros_result_t gpio_result = args->api->gpio_close(args->context, state->gpio);
        if (!result)
            result = gpio_result;
    }
    return result;
}
/** @brief Revision-2 host service demonstrating bounded timers and simulated GPIO. */
static const micros_service_descriptor_t descriptor = {
    .struct_bytes = sizeof(micros_service_descriptor_t),
    .abi_major = MICROS_ABI_MAJOR,
    .abi_revision = MICROS_ABI_REVISION,
    .target = MICROS_BUILD_TARGET,
    .arena_bytes = sizeof(runtime_service_state_t),
    .arena_alignment = _Alignof(runtime_service_state_t),
    .stack_bytes = SERVICE_STACK_BYTES,
    .init = initialize,
    .start = start,
    .step = step,
    .stop = stop};
const micros_service_descriptor_t *micros_service_query(void)
{
    return &descriptor;
}
