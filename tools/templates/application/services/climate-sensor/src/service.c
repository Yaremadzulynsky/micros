#include "climate_hooks.h"

static micros_result_t sample(const micros_service_args_t *service,
                             micros_handle_t timer, void *user_data)
{
    (void)timer;
    climate_context_t *ctx = user_data;
    simulated_sample_t value = simulated_sensor_read(&ctx->state.sensor);
    climate_climate_reading_message_t message = {0};
    message.sequence = ++ctx->state.sequence;
    message.sampled_ms = (uint32_t)(service->api->monotonic_us(service->context) / 1000);
    message.temperature_millicelsius = value.temperature_millicelsius;
    message.humidity_permille = value.humidity_permille;
    return climate_climate_reading_publish(service, ctx->port_climate_reading, &message);
}
micros_result_t climate_on_start(climate_context_t *ctx)
{
    simulated_sensor_reset(&ctx->state.sensor);
    ctx->state.sequence = 0;
    uint64_t period = (uint64_t)ctx->config.interval_ms * 1000;
    return climate_timer_sample_open(ctx, period, period, sample, ctx);
}
micros_result_t climate_on_step(climate_context_t *ctx) { (void)ctx; return MICROS_OK; }
micros_result_t climate_on_stop(climate_context_t *ctx) { (void)ctx; return MICROS_OK; }
