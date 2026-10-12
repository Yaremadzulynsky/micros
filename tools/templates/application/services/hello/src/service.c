#include "hello_hooks.h"
#include <stddef.h>

static micros_result_t greet(const micros_service_args_t *service,
                             micros_handle_t timer, void *user_data)
{
    (void)timer;
    (void)user_data;
    static const uint8_t message[] = "Hello world\n";
    return service->api->debug_write(service->context, message, sizeof(message) - 1);
}

micros_result_t hello_on_start(hello_context_t *ctx)
{
    /* The project selects milliseconds; the timer API uses microseconds. */
    uint64_t period_us = (uint64_t)ctx->config.interval_ms * 1000;
    return hello_timer_greeting_open(ctx, period_us, period_us, greet, NULL);
}

micros_result_t hello_on_step(hello_context_t *ctx)
{
    (void)ctx; /* The timer handles the work; no polling loop is needed. */
    return MICROS_OK;
}

micros_result_t hello_on_stop(hello_context_t *ctx)
{
    (void)ctx; /* Micros closes the declared timer after this hook. */
    return MICROS_OK;
}
