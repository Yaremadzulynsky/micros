#include "fan_hooks.h"
micros_result_t fan_on_start(fan_context_t *ctx)
{
    ctx->state.enabled = false;
    return ctx->config.off_millicelsius < ctx->config.on_millicelsius
        ? MICROS_OK : MICROS_ERROR_INVALID_ARGUMENT;
}
micros_result_t fan_on_climate_reading(fan_context_t *ctx,
                                     const fan_climate_reading_message_t *reading)
{
    if (reading->temperature_millicelsius >= (int32_t)ctx->config.on_millicelsius)
        ctx->state.enabled = true;
    else if (reading->temperature_millicelsius <= (int32_t)ctx->config.off_millicelsius)
        ctx->state.enabled = false;
    fan_fan_status_message_t status = {0};
    status.reading_sequence = reading->sequence;
    status.sampled_ms = reading->sampled_ms;
    status.enabled = ctx->state.enabled;
    return fan_fan_status_publish(ctx->service, ctx->port_fan_status, &status);
}
micros_result_t fan_on_climate_reading_lost(fan_context_t *ctx)
{
    /* A latest channel may skip samples. Apply policy to the next current value. */
    (void)ctx; return MICROS_OK;
}
micros_result_t fan_on_step(fan_context_t *ctx) { (void)ctx; return MICROS_OK; }
micros_result_t fan_on_stop(fan_context_t *ctx) { (void)ctx; return MICROS_OK; }
