#include "../generated/colors_ipc.h"
#include "button_input.h"

micros_result_t subscribe_to_button(const micros_service_args_t *args, button_input_t *button)
{
    /* Retained states establish a baseline, but must never replay actions. */
    button->subscribed_us = args->api->monotonic_us(args->context);
    return colors_button_open(args, &button->subscription);
}

micros_result_t read_button_press(const micros_service_args_t *args, button_input_t *button,
                                 bool *pressed)
{
    *pressed = false;
    colors_button_message_t button_state;
    micros_result_t result = colors_button_read(args, button->subscription, &button_state);
    if (result == MICROS_ERROR_EMPTY)
        return MICROS_OK;
    if (result == MICROS_ERROR_MESSAGES_MISSED) {
        button->has_baseline = false; /* Lost history must not invent a new press edge. */
        return MICROS_OK;
    }
    if (result)
        return result;
    if (!button_state.sequence || !button_state.publisher_started_us ||
        button_state.monotonic_us < button_state.publisher_started_us ||
        button_state.monotonic_us <= button->last_sample_us)
        return MICROS_ERROR_SERVICE;
    bool same_publisher = button->publisher_started_us == button_state.publisher_started_us;
    if (same_publisher && button_state.sequence <= button->last_sequence)
        return MICROS_ERROR_SERVICE;
    if (!same_publisher && button_state.publisher_started_us < button->publisher_started_us)
        return MICROS_ERROR_SERVICE;
    bool contiguous = same_publisher && button_state.sequence == button->last_sequence + 1;
    bool stable_pressed = button_state.pressed;
    *pressed = button->has_baseline && contiguous &&
        button_state.monotonic_us > button->subscribed_us &&
        !button->stable_pressed && stable_pressed;
    button->publisher_started_us = button_state.publisher_started_us;
    button->has_baseline = true;
    button->stable_pressed = stable_pressed;
    button->last_sequence = button_state.sequence;
    button->last_sample_us = button_state.monotonic_us;
    return MICROS_OK;
}

micros_result_t unsubscribe_from_button(const micros_service_args_t *args, button_input_t *button)
{
    return button->subscription ? colors_button_close(args, button->subscription)
                                : MICROS_OK;
}
