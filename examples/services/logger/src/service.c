#include "../generated/logger_ipc.h"

/* Freestanding services use the runtime's 4 KiB minimum task stack. */
#define SERVICE_STACK_BYTES 4096u
#ifndef MICROS_SERVICE_TARGET
#define MICROS_SERVICE_TARGET MICROS_BUILD_TARGET
#endif

/** @brief Arena-owned subscription and last decoded sequence for ordering checks. */
typedef struct {
    micros_handle_t channel;
    uint32_t sequence;
    uint64_t publisher_started_us;
    uint64_t last_sample_us;
} logger_state_t;

/** @brief Emit measured publish-to-decode delay without a libc formatting dependency. */
static micros_result_t report_latency(const micros_service_args_t *args, uint64_t published_us)
{
    uint64_t elapsed_us = args->api->monotonic_us(args->context) - published_us;
    /* Twenty decimal digits cover uint64_t; include the prefix and newline. */
    uint8_t message[32] = "LATENCY_US=";
    uint8_t reversed_digits[20];
    unsigned digit_count = 0;
    do {
        reversed_digits[digit_count++] = (uint8_t)('0' + elapsed_us % 10);
        elapsed_us /= 10;
    } while (elapsed_us);
    unsigned message_bytes = sizeof("LATENCY_US=") - 1;
    while (digit_count)
        message[message_bytes++] = reversed_digits[--digit_count];
    message[message_bytes++] = '\n';
    return args->api->debug_write(args->context, message, message_bytes);
}
static micros_result_t initialize(const micros_service_args_t *args)
{
    logger_state_t *state = args->arena;
    return logger_button_open(args, &state->channel);
}
static micros_result_t start(const micros_service_args_t *args)
{
    (void)args;
    return MICROS_OK;
}
/** @brief Read the next confirmed button state and report its publish-to-read latency. */
static micros_result_t step(const micros_service_args_t *args)
{
    logger_state_t *state = args->arena;
    logger_button_message_t button_state;
    micros_result_t result = logger_button_read(args, state->channel, &button_state);
    if (result == MICROS_ERROR_EMPTY)
        return MICROS_OK;
    if (result == MICROS_ERROR_MESSAGES_MISSED) {
        static const uint8_t warning[] = "fast logger: messages missed\n";
        return args->api->debug_write(args->context, warning, sizeof(warning) - 1);
    }
    if (result)
        return result;
    if (!button_state.sequence || !button_state.publisher_started_us ||
        button_state.monotonic_us < button_state.publisher_started_us ||
        button_state.monotonic_us <= state->last_sample_us ||
        button_state.publisher_started_us < state->publisher_started_us ||
        (button_state.publisher_started_us == state->publisher_started_us &&
         button_state.sequence <= state->sequence))
        return MICROS_ERROR_SERVICE;
    state->sequence = button_state.sequence;
    state->publisher_started_us = button_state.publisher_started_us;
    state->last_sample_us = button_state.monotonic_us;
    return report_latency(args, button_state.monotonic_us);
}
static micros_result_t stop(const micros_service_args_t *args)
{
    logger_state_t *state = args->arena;
    return state->channel ? logger_button_close(args, state->channel) : MICROS_OK;
}
/** @brief Logger implementation of the shared native service interface. */
static const micros_service_descriptor_t descriptor = {
    .struct_bytes = sizeof(micros_service_descriptor_t),
    .abi_major = MICROS_ABI_MAJOR,
    .abi_revision = MICROS_ABI_REVISION,
    .target = MICROS_SERVICE_TARGET,
    .arena_bytes = sizeof(logger_state_t),
    .arena_alignment = _Alignof(logger_state_t),
    .stack_bytes = SERVICE_STACK_BYTES,
    .init = initialize,
    .start = start,
    .step = step,
    .stop = stop};
const micros_service_descriptor_t *micros_service_query(void)
{
    return &descriptor;
}
