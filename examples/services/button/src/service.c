#include "../generated/button_ipc.h"

#include "button_state.h"
#ifndef MICROS_SERVICE_TARGET
#define MICROS_SERVICE_TARGET MICROS_BUILD_TARGET
#endif

/** @brief Read hardware and publish only confirmed button state changes. */
static micros_result_t publish_button_state(const micros_service_args_t *args, micros_handle_t timer,
                                      void *user_data)
{
    (void)timer;
    button_state_t *state = user_data;
    uint32_t button_level;
    micros_result_t result = args->api->gpio_read(args->context, state->gpio, &button_level);
    if (result)
        return result;
    uint64_t confirmed_us = args->api->monotonic_us(args->context);
    /* Pull-up makes a pressed button low; debounce belongs to this publisher. */
    if (!confirm_button_state(&state->debounce, button_level == 0, confirmed_us,
                              state->config.debounce_ms * BUTTON_US_PER_MS))
        return MICROS_OK;
    if (state->sequence == UINT32_MAX) {
        state->sequence = 0;
        state->publisher_started_us = confirmed_us;
    }
    button_button_message_t message = {
        .sequence = ++state->sequence,
        .monotonic_us = confirmed_us,
        .pressed = state->debounce.stable_pressed,
        .publisher_started_us = state->publisher_started_us,
    };
    return button_button_publish(args, state->channel, &message);
}
static micros_result_t initialize(const micros_service_args_t *args)
{
    button_state_t *state = args->arena;
    micros_result_t result =
        button_config_decode(args->config_data, args->config_bytes, &state->config);
    if (result)
        return result;
    result = button_user_button_open(args, &state->gpio);
    return result ? result : button_button_open(args, &state->channel);
}
static micros_result_t start(const micros_service_args_t *args)
{
    button_state_t *state = args->arena;
    state->publisher_started_us = args->api->monotonic_us(args->context);
    if (!state->publisher_started_us) state->publisher_started_us = 1;
    /* Start sampling immediately; the initial state is published after debounce. */
    return args->api->timer_open(args->context, 0, state->config.sample_interval_ms * BUTTON_US_PER_MS,
                                 publish_button_state,
                                 state, &state->timer);
}
static micros_result_t step(const micros_service_args_t *args)
{
    (void)args; /* Sampling runs through the runtime-owned timer callback. */
    return MICROS_OK;
}
static micros_result_t stop(const micros_service_args_t *args)
{
    button_state_t *state = args->arena;
    micros_result_t result = MICROS_OK;
    if (state->gpio) {
        result = args->api->gpio_close(args->context, state->gpio);
        if (result)
            return result;
    }
    if (state->timer)
        result = args->api->timer_close(args->context, state->timer);
    if (state->channel) {
        micros_result_t close_result = button_button_close(args, state->channel);
        if (!result)
            result = close_result;
    }
    return result;
}
/** @brief Button implementation of the shared native service interface. */
static const micros_service_descriptor_t descriptor = {
    .struct_bytes = sizeof(micros_service_descriptor_t),
    .abi_major = MICROS_ABI_MAJOR,
    .abi_revision = MICROS_ABI_REVISION,
    .target = MICROS_SERVICE_TARGET,
    .arena_bytes = sizeof(button_state_t),
    .arena_alignment = _Alignof(button_state_t),
    .stack_bytes = SERVICE_STACK_BYTES,
    .init = initialize,
    .start = start,
    .step = step,
    .stop = stop};
const micros_service_descriptor_t *micros_service_query(void)
{
    return &descriptor;
}
