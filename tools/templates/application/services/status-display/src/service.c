#include "display_hooks.h"

/* Bounded integer output avoids floating-point formatting on small boards. */
static char *text(char *out, const char *value)
{
    while (*value) *out++ = *value++;
    return out;
}
static char *number(char *out, uint32_t value)
{
    char digits[10]; unsigned count = 0;
    do { digits[count++] = (char)('0' + value % 10); value /= 10; } while (value);
    while (count) *out++ = digits[--count];
    return out;
}
micros_result_t display_on_start(display_context_t *ctx) { (void)ctx; return MICROS_OK; }
micros_result_t display_on_climate_reading(display_context_t *ctx,
                                         const display_climate_reading_message_t *message)
{
    ctx->state.reading = *message;
    ctx->state.have_reading = ctx->state.dirty = true;
    return MICROS_OK;
}
micros_result_t display_on_fan_status(display_context_t *ctx,
                                    const display_fan_status_message_t *message)
{
    ctx->state.fan = *message;
    ctx->state.have_fan = ctx->state.dirty = true;
    return MICROS_OK;
}
micros_result_t display_on_step(display_context_t *ctx)
{
    display_state_t *s = &ctx->state;
    if (!s->have_reading || !s->have_fan) return MICROS_OK;
    uint32_t now = (uint32_t)(ctx->service->api->monotonic_us(ctx->service->context) / 1000);
    if ((uint32_t)(now - s->reading.sampled_ms) > ctx->config.stale_after_ms ||
        (uint32_t)(now - s->fan.sampled_ms) > ctx->config.stale_after_ms) {
        if (s->stale) return MICROS_OK;
        s->stale = true;
        static const uint8_t warning[] = "Simulated climate: stale data; waiting for fresh readings\n";
        return ctx->service->api->debug_write(ctx->service->context, warning, sizeof(warning)-1);
    }
    /* Independent channels are not an atomic snapshot. Wait for matching samples. */
    if (!s->dirty || s->reading.sequence != s->fan.reading_sequence ||
        s->reading.sampled_ms != s->fan.sampled_ms) return MICROS_OK;
    s->dirty = s->stale = false;
    char line[112], *out = text(line, "Simulated climate #");
    out = number(out, s->reading.sequence);
    out = text(out, ": temp=");
    int32_t temperature = s->reading.temperature_millicelsius;
    if (temperature < 0) *out++ = '-';
    out = number(out, temperature < 0 ? 0u-(uint32_t)temperature : (uint32_t)temperature);
    out = text(out, " mC humidity="); out = number(out, s->reading.humidity_permille);
    out = text(out, " permille fan="); out = text(out, s->fan.enabled ? "ON\n" : "OFF\n");
    return ctx->service->api->debug_write(ctx->service->context, (const uint8_t *)line, (uint32_t)(out-line));
}
micros_result_t display_on_climate_reading_lost(display_context_t *ctx)
{ ctx->state.have_reading = false; return MICROS_OK; }
micros_result_t display_on_fan_status_lost(display_context_t *ctx)
{ ctx->state.have_fan = false; return MICROS_OK; }
micros_result_t display_on_stop(display_context_t *ctx) { (void)ctx; return MICROS_OK; }
