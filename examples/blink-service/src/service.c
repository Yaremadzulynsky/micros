#include "../generated/blink_resources.h"
#include <micros/service.h>

typedef struct
{
    micros_handle_t timer, led;
    uint32_t level;
} blink_state_t;
static micros_result_t tick(const micros_service_args_t *args, micros_handle_t timer, void *data)
{
    (void)timer;
    (void)data;
    blink_state_t *state = args->arena;
    state->level ^= 1;
    return args->api->gpio_write(args->context, state->led, state->level);
}
static micros_result_t initialize(const micros_service_args_t *args)
{
    (void)args;
    return MICROS_OK;
}
static micros_result_t start(const micros_service_args_t *args)
{
    blink_state_t *state = args->arena;
    micros_result_t result = blink_led_open(args, &state->led);
    return result ? result
                  : args->api->timer_open(args->context, 250000, 250000, tick, 0, &state->timer);
}
static micros_result_t step(const micros_service_args_t *args)
{
    (void)args;
    return MICROS_OK;
}
static micros_result_t stop(const micros_service_args_t *args)
{
    blink_state_t *state = args->arena;
    if (state->timer)
        args->api->timer_close(args->context, state->timer);
    if (state->led)
    {
        args->api->gpio_write(args->context, state->led, 0);
        args->api->gpio_close(args->context, state->led);
    }
    return MICROS_OK;
}
const micros_service_descriptor_t micros_descriptor = {sizeof(micros_service_descriptor_t),
                                                       MICROS_ABI_MAJOR,
                                                       MICROS_ABI_REVISION,
                                                       MICROS_BUILD_TARGET,
                                                       sizeof(blink_state_t),
                                                       _Alignof(blink_state_t),
                                                       2048,
                                                       0,
                                                       initialize,
                                                       start,
                                                       step,
                                                       stop};
const micros_service_descriptor_t *micros_service_query(void) { return &micros_descriptor; }
