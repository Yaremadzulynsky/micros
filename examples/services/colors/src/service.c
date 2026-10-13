#include "color_service.h"

#define COLOR_REPORT_INTERVAL_US UINT64_C(10000000)

static micros_result_t initialize(const micros_service_args_t *service_args)
{
    color_service_t *state = service_args->arena;
    micros_result_t result = colors_config_decode(service_args->config_data,
                                                   service_args->config_bytes, &state->config);
    if (result)
        return result;
    configure_palette(&state->palette, &state->config);
    result = subscribe_to_button(service_args, &state->button);
    if (!result)
        result = neopixel_open(service_args, &state->pixel);
    return result;
}

static micros_result_t start(const micros_service_args_t *service_args)
{
    color_service_t *state = service_args->arena;
    state->last_report_us = service_args->api->monotonic_us(service_args->context);
    return show_current_color(service_args, &state->palette);
}

static micros_result_t step(const micros_service_args_t *service_args)
{
    color_service_t *state = service_args->arena;
    bool pressed;
    micros_result_t result = read_button_press(service_args, &state->button, &pressed);
    if (result)
        return result;
    if (pressed) {
        select_next_color(&state->palette);
        result = show_current_color(service_args, &state->palette);
        if (result)
            return result;
    }
    uint64_t now = service_args->api->monotonic_us(service_args->context);
    if (now - state->last_report_us >= COLOR_REPORT_INTERVAL_US) {
        state->last_report_us = now;
        if (!pressed)
            return report_current_color(service_args, &state->palette);
    }
    return MICROS_OK;
}

static micros_result_t stop(const micros_service_args_t *service_args)
{
    color_service_t *state = service_args->arena;
    neopixel_close(service_args, &state->pixel);
    return unsubscribe_from_button(service_args, &state->button);
}

/** @brief Native lifecycle interface for the Feather V2 button-controlled pixel. */
const micros_service_descriptor_t micros_descriptor = {
    .struct_bytes = sizeof(micros_service_descriptor_t),
    .abi_major = MICROS_ABI_MAJOR,
    .abi_revision = MICROS_ABI_REVISION,
    .target = MICROS_SERVICE_TARGET,
    .arena_bytes = sizeof(color_service_t),
    .arena_alignment = _Alignof(color_service_t),
    .stack_bytes = COLOR_SERVICE_STACK_BYTES,
    .reserved = 0,
    .init = initialize,
    .start = start,
    .step = step,
    .stop = stop,
};

const micros_service_descriptor_t *micros_service_query(void)
{
    return &micros_descriptor;
}
