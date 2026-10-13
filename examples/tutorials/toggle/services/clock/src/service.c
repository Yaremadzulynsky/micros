#include "clock_hooks.h"

static micros_result_t tick(const micros_service_args_t *args,
                           micros_handle_t timer, void *data)
{
    (void)timer;
    clock_context_t *ctx = data;
    clock_toggle_message_t event = {
        .emitted_us = args->api->monotonic_us(args->context)
    };
    return clock_toggle_publish(args, ctx->port_toggle, &event);
}

micros_result_t clock_on_start(clock_context_t *ctx)
{
    uint64_t period_us = (uint64_t)ctx->config.interval_ms * 1000u;
    return clock_timer_tick_open(ctx, period_us, period_us, tick, ctx);
}

micros_result_t clock_on_step(clock_context_t *ctx)
{
    (void)ctx;
    return MICROS_OK;
}

micros_result_t clock_on_stop(clock_context_t *ctx)
{
    (void)ctx; /* Generated hooks close the timer and publication. */
    return MICROS_OK;
}
