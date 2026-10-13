#include "button_state.codec.h"
/* Match the fixture channel capacity, including room for unknown protobuf fields. */
#define TEST_MESSAGE_CAPACITY 64u
/* Internal fault/transport fixture deliberately exercises raw ABI dispatch. */
#include "../../../../src/sdk/abi/internal/micros/ipc.h"
/* These are graph fixtures, not global policy: channel 1 represents button.state,
 * the publisher runs at 10 Hz, and a slow subscriber pauses beyond eight samples. */
#define DEMO_CHANNEL_KEY 1u
#ifndef SAMPLE_PERIOD_US
#define SAMPLE_PERIOD_US UINT64_C(100000)
#endif
#define SLOW_READER_PAUSE_US UINT64_C(1200000)
#define DEMO_STACK_BYTES 4096u /* Small freestanding service; M2 admission minimum. */
#ifndef MICROS_SERVICE_TARGET
#define MICROS_SERVICE_TARGET MICROS_BUILD_TARGET
#endif
/* Hardware builds use the BSP's logical button input and red LED output. */
#ifndef DEMO_LED_LINE
#define DEMO_LED_LINE 0u
#endif
#ifndef DEMO_BUTTON_LINE
#define DEMO_BUTTON_LINE 1u
#endif
#ifndef LED_HALF_PERIOD_SAMPLES
#define LED_HALF_PERIOD_SAMPLES 5u /* Five 100 ms samples per half-cycle: 1 Hz blink. */
#endif
#ifndef PIPELINE_ROLE
#define PIPELINE_ROLE 0 /* 0 publisher, 1 fast logger, 2 deliberately slow logger. */
#endif
#define WRITE_LITERAL(args, text)                                                                  \
    ((args)->api->debug_write((args)->context, (const uint8_t *)(text), sizeof(text) - 1))

/** @brief One pipeline participant's arena-owned channel/timer state and sample progress. */
typedef struct {
    micros_handle_t channel;
    micros_handle_t timer;
    uint64_t read_after_us;
    uint32_t sequence;
#ifdef PIPELINE_HARDWARE
    micros_handle_t gpio;
#endif
} pipeline_state_t;

#ifdef PIPELINE_HARDWARE
/** @brief Emit measured publish-to-decode delay without a libc formatting dependency. */
static micros_result_t report_latency(const micros_service_args_t *args, uint64_t published_us)
{
    uint64_t elapsed_us = args->api->monotonic_us(args->context) - published_us;
    /* Twenty decimal digits cover uint64_t; include the prefix and newline. */
    uint8_t message[32] = "LATENCY_US=";
    uint8_t reversed[20];
    unsigned digits = 0;
    do {
        reversed[digits++] = (uint8_t)('0' + elapsed_us % 10);
        elapsed_us /= 10;
    } while (elapsed_us);
    unsigned length = sizeof("LATENCY_US=") - 1;
    while (digits)
        message[length++] = reversed[--digits];
    message[length++] = '\n';
    return args->api->debug_write(args->context, message, length);
}
#endif
static micros_result_t publish_sample(const micros_service_args_t *args, micros_handle_t timer,
                                      void *user_data)
{
    (void)timer;
    pipeline_state_t *state = user_data;
    /* Alternate synthetic button states to exercise stream delivery. */
    micros_button_v1_ButtonState sample = {++state->sequence, args->api->monotonic_us(args->context),
                              (state->sequence % 2) != 0, state->read_after_us};
#ifdef PIPELINE_HARDWARE
    uint32_t button_level;
    micros_result_t gpio_result = args->api->gpio_read(args->context, state->gpio, &button_level);
    if (gpio_result)
        return gpio_result;
    sample.pressed = button_level == 0; /* Board pull-up makes a pressed button low. */
#endif
    uint8_t encoded[TEST_MESSAGE_CAPACITY];
    uint32_t bytes;
    micros_result_t result = micros_button_v1_ButtonState_encode(&sample, encoded, sizeof(encoded), &bytes);
    return result ? result : args->api->_ipc->ipc_publish(args->context, state->channel, encoded, bytes);
}
static micros_result_t initialize(const micros_service_args_t *args)
{
    pipeline_state_t *state = args->arena;
#ifdef PIPELINE_HARDWARE
    if (PIPELINE_ROLE == 0 || PIPELINE_ROLE == 3) {
        micros_result_t result = args->api->gpio_open(
            args->context, PIPELINE_ROLE == 0 ? DEMO_BUTTON_LINE : DEMO_LED_LINE, &state->gpio);
        if (result)
            return result;
    }
#endif
    return args->api->_ipc->ipc_open(args->context, DEMO_CHANNEL_KEY,
                               PIPELINE_ROLE == 0 ? MICROS_IPC_PUBLISH : MICROS_IPC_SUBSCRIBE,
                               &state->channel);
}
static micros_result_t start(const micros_service_args_t *args)
{
    pipeline_state_t *state = args->arena;
    if (PIPELINE_ROLE == 0) {
        state->read_after_us = args->api->monotonic_us(args->context);
        if (!state->read_after_us) state->read_after_us = 1;
        return args->api->timer_open(args->context, 0, SAMPLE_PERIOD_US, publish_sample, state,
                                     &state->timer);
    }
    state->read_after_us =
        args->api->monotonic_us(args->context) + (PIPELINE_ROLE == 2 ? SLOW_READER_PAUSE_US : 0);
    return MICROS_OK;
}
static micros_result_t step(const micros_service_args_t *args)
{
    if (PIPELINE_ROLE == 0)
        return MICROS_OK;
    pipeline_state_t *state = args->arena;
    if (args->api->monotonic_us(args->context) < state->read_after_us)
        return MICROS_OK;
    uint8_t encoded[TEST_MESSAGE_CAPACITY];
    uint32_t bytes;
    micros_message_info_t info;
    micros_result_t result =
        args->api->_ipc->ipc_read(args->context, state->channel, encoded, sizeof(encoded), &bytes, &info);
    if (result == MICROS_ERROR_EMPTY)
        return MICROS_OK;
    if (result == MICROS_ERROR_MESSAGES_MISSED)
        return PIPELINE_ROLE == 2 ? WRITE_LITERAL(args, "slow logger: messages missed\n")
                                  : WRITE_LITERAL(args, "fast logger: messages missed\n");
    if (result)
        return result;
    micros_button_v1_ButtonState sample;
    result = micros_button_v1_ButtonState_decode(encoded, bytes, &sample);
    if (result || sample.sequence <= state->sequence || !sample.monotonic_us)
        return MICROS_ERROR_SERVICE;
    state->sequence = sample.sequence;
#ifdef PIPELINE_HARDWARE
    if (PIPELINE_ROLE == 1)
        return report_latency(args, sample.monotonic_us);
    if (PIPELINE_ROLE == 3) {
        uint32_t level =
            sample.pressed ? 1 : (sample.sequence / LED_HALF_PERIOD_SAMPLES) % 2;
        result = args->api->gpio_write(args->context, state->gpio, level);
        uint32_t observed_level = 0;
        if (!result)
            result = args->api->gpio_read(args->context, state->gpio, &observed_level);
        if (result || observed_level != level)
            return MICROS_ERROR_SERVICE;
        return level ? WRITE_LITERAL(args, "LED level=1 verified\n")
                     : WRITE_LITERAL(args, "LED level=0 verified\n");
    }
#endif
    return PIPELINE_ROLE == 2 ? WRITE_LITERAL(args, "slow logger: sample decoded\n")
                              : WRITE_LITERAL(args, "fast logger: sample decoded\n");
}
static micros_result_t stop(const micros_service_args_t *args)
{
    pipeline_state_t *state = args->arena;
    micros_result_t result = MICROS_OK;
#ifdef PIPELINE_HARDWARE
    if (state->gpio) {
        result = args->api->gpio_close(args->context, state->gpio);
        if (result)
            return result;
    }
#endif
    if (state->timer)
        result = args->api->timer_close(args->context, state->timer);
    if (state->channel) {
        micros_result_t close_result = args->api->_ipc->ipc_close(args->context, state->channel);
        if (!result)
            result = close_result;
    }
    return result;
}
/** @brief Publisher/logger implementation of the shared native service interface. */
static const micros_service_descriptor_t descriptor = {
    .struct_bytes = sizeof(micros_service_descriptor_t),
    .abi_major = MICROS_ABI_MAJOR,
    .abi_revision = MICROS_ABI_REVISION,
    .target = MICROS_SERVICE_TARGET,
    .arena_bytes = sizeof(pipeline_state_t),
    .arena_alignment = _Alignof(pipeline_state_t),
    .stack_bytes = DEMO_STACK_BYTES,
    .init = initialize,
    .start = start,
    .step = step,
    .stop = stop};
const micros_service_descriptor_t *micros_service_query(void)
{
    return &descriptor;
}
