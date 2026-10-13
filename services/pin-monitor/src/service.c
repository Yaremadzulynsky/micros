#include "../generated/monitor_config.h"
#include "../generated/monitor_resources.h"
#include "../generated/monitor_ipc.h"

_Static_assert(MONITOR_GPIO_COUNT > 0 && MONITOR_GPIO_COUNT <= 4, "Monitor one to four inputs");
#define INPUT_ONLY(index, prefix, pin, output) _Static_assert(!output, "Monitor requires input GPIO grants");
MONITOR_GPIO_PINS(INPUT_ONLY)
#undef INPUT_ONLY
#define PIN_NUMBER(index, prefix, pin, output) pin,
static const uint32_t pins[] = {MONITOR_GPIO_PINS(PIN_NUMBER)};
#undef PIN_NUMBER

typedef struct {
    monitor_config_t config;
    micros_handle_t gpio[MONITOR_GPIO_COUNT], samples;
    uint64_t due, epoch;
    uint32_t sequence;
} state_t;

static micros_result_t initialize(const micros_service_args_t *args)
{
    state_t *state = args->arena;
    micros_result_t result = monitor_config_decode(args->config_data, args->config_bytes, &state->config);
    if (result) return result;
    if (state->config.analog_mask >> MONITOR_GPIO_COUNT) return MICROS_ERROR_INVALID_ARGUMENT;
    /* The mask indexes the GPIO grant list, not physical pin numbers. */
    for (unsigned i = 0; i < MONITOR_GPIO_COUNT; ++i) {
        if ((state->config.analog_mask & (1u << i)) &&
            (pins[i] < 32 || pins[i] > 39 || !args->api->gpio_read_analog))
            return MICROS_ERROR_UNSUPPORTED;
    }
#define OPEN(index, prefix, pin, output) \
    if (!result) result = prefix##_open(args, &state->gpio[index]);
    MONITOR_GPIO_PINS(OPEN)
#undef OPEN
    if (result) return result;
    /* Validate/configure ADCs at initialization; no ADC setup in the sampling loop. */
    for (unsigned i = 0; i < MONITOR_GPIO_COUNT; ++i) {
        if (!(state->config.analog_mask & (1u << i))) continue;
        uint32_t ignored;
        result = args->api->gpio_read_analog(args->context, state->gpio[i], &ignored);
        if (result && result != MICROS_ERROR_BUSY) return result;
    }
    return monitor_samples_open(args, &state->samples);
}

static micros_result_t start(const micros_service_args_t *args)
{
    state_t *state = args->arena;
    state->due = args->api->monotonic_us(args->context);
    state->epoch = state->due ? state->due : 1;
    state->sequence = 0;
    return MICROS_OK;
}

static micros_result_t step(const micros_service_args_t *args)
{
    state_t *state = args->arena;
    uint64_t now = args->api->monotonic_us(args->context);
    if (now < state->due) return MICROS_OK;
    /* Coalesce late scans; never burst to catch up missed intervals. */
    state->due = now + (uint64_t)state->config.sample_interval_ms * 1000u;
    if (state->sequence == UINT32_MAX) {
        state->sequence = 0;
        state->epoch = now ? now : 1;
    }
    ++state->sequence;
    for (unsigned i = 0; i < MONITOR_GPIO_COUNT; ++i) {
        monitor_samples_message_t sample = {
            .sequence = state->sequence, .publisher_started_us = state->epoch,
            .pin = pins[i], .analog = (state->config.analog_mask & (1u << i)) != 0,
        };
        sample.error = sample.analog
            ? args->api->gpio_read_analog(args->context, state->gpio[i], &sample.value)
            : args->api->gpio_read(args->context, state->gpio[i], &sample.value);
        if (sample.error) sample.value = 0;
        sample.monotonic_us = args->api->monotonic_us(args->context);
        micros_result_t result = monitor_samples_publish(args, state->samples, &sample);
        if (result) return result;
    }
    return MICROS_OK;
}

static micros_result_t stop(const micros_service_args_t *args)
{
    state_t *state = args->arena;
    micros_result_t result = MICROS_OK;
    for (unsigned i = 0; i < MONITOR_GPIO_COUNT; ++i) {
        if (!state->gpio[i]) continue;
        micros_result_t closed = args->api->gpio_close(args->context, state->gpio[i]);
        if (!closed) state->gpio[i] = 0;
        if (!result) result = closed;
    }
    if (state->samples) {
        micros_result_t closed = monitor_samples_close(args, state->samples);
        if (!closed) state->samples = 0;
        if (!result) result = closed;
    }
    return result;
}

const micros_service_descriptor_t micros_descriptor = {
    .struct_bytes = sizeof(micros_service_descriptor_t),
    .abi_major = MICROS_ABI_MAJOR, .abi_revision = MICROS_ABI_REVISION,
    .target = MICROS_BUILD_TARGET,
    .arena_bytes = sizeof(state_t), .arena_alignment = _Alignof(state_t), .stack_bytes = 2048,
    .init = initialize, .start = start, .step = step, .stop = stop,
};
const micros_service_descriptor_t *micros_service_query(void) { return &micros_descriptor; }
