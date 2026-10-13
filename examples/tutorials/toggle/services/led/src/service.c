#include "led_hooks.h"

micros_result_t led_on_toggle(led_context_t *ctx,
                              const led_toggle_message_t *event)
{
    if (event->emitted_us <= ctx->state.started_us) return MICROS_OK;
    ctx->state.level ^= 1u;
    return led_led_write(ctx->service, ctx->gpio_led, ctx->state.level);
}

micros_result_t led_on_start(led_context_t *ctx)
{
    ctx->state.started_us = ctx->service->api->monotonic_us(ctx->service->context);
    ctx->state.level = 0;
    return led_led_write(ctx->service, ctx->gpio_led, 0);
}

micros_result_t led_on_toggle_lost(led_context_t *ctx)
{
    static const uint8_t message[] = "Toggle events lost; restart the application.\n";
    (void)ctx->service->api->debug_write(ctx->service->context,
                                       message, sizeof(message) - 1u);
    return MICROS_ERROR_MESSAGES_MISSED;
}

micros_result_t led_on_step(led_context_t *ctx)
{
    (void)ctx;
    return MICROS_OK;
}

micros_result_t led_on_stop(led_context_t *ctx)
{
    return led_led_write(ctx->service, ctx->gpio_led, 0);
}
