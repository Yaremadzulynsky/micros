#include "button_hooks.h"

static micros_result_t sample(const micros_service_args_t *args,
                             micros_handle_t timer, void *data)
{
    (void)timer;
    button_context_t *ctx = data;
    uint32_t level;
    micros_result_t result = button_button_read(args, ctx->gpio_button, &level);
    if (result) return result;
    bool pressed = (level == 0);
    uint64_t now = args->api->monotonic_us(args->context);
    if (!button_confirm(&ctx->state, pressed, now,
                        (uint64_t)ctx->config.debounce_ms * 1000u))
        return MICROS_OK;
    if (!ctx->state.pressed) return MICROS_OK;
    button_toggle_message_t event = { .emitted_us = now };
    return button_toggle_publish(args, ctx->port_toggle, &event);
}

micros_result_t button_on_start(button_context_t *ctx)
{
    ctx->state = (button_state_t){0};
    uint64_t period_us = (uint64_t)ctx->config.sample_ms * 1000u;
    return button_timer_sample_open(ctx, 0, period_us, sample, ctx);
}

micros_result_t button_on_step(button_context_t *ctx)
{
    (void)ctx;
    return MICROS_OK;
}

micros_result_t button_on_stop(button_context_t *ctx)
{
    (void)ctx; /* Generated hooks close the timer, input and publication. */
    return MICROS_OK;
}
