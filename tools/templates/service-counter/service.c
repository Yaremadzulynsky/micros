#include "counter_hooks.h"

micros_result_t counter_on_start(counter_context_t *ctx)
{
    (void)ctx;
    return MICROS_OK;
}

micros_result_t counter_on_step(counter_context_t *ctx)
{
    (void)ctx; /* Micros dispatches declared commands to the handlers below. */
    return MICROS_OK;
}

micros_result_t counter_on_stop(counter_context_t *ctx)
{
    (void)ctx;
    return MICROS_OK;
}

micros_result_t counter_handle_read(counter_context_t *ctx, counter_count_t *out_count)
{
    *out_count = ctx->state.count;
    return MICROS_OK;
}

micros_result_t counter_handle_increment(counter_context_t *ctx, counter_count_t *out_count)
{
    *out_count = ++ctx->state.count; /* Unsigned wraparound; resets on restart. */
    return MICROS_OK;
}

micros_result_t counter_handle_reset(counter_context_t *ctx, counter_count_t *out_count)
{
    ctx->state.count = 0;
    *out_count = 0;
    return MICROS_OK;
}
