#include "../../services/pin-monitor/src/service.c"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static uint64_t now = 1000;
static unsigned opened, closed, count, fail_line = UINT32_MAX;
static micros_result_t analog_result;
static monitor_samples_message_t messages[32];
static uint64_t clock_us(micros_context_t *context) { (void)context; return now; }
static micros_result_t open_pin(micros_context_t *context, uint32_t line, micros_handle_t *handle)
{
    (void)context;
    if (line == fail_line) return MICROS_ERROR_BUSY;
    *handle = line + 1;
    ++opened;
    return MICROS_OK;
}
static micros_result_t close_pin(micros_context_t *context, micros_handle_t handle)
{ (void)context; assert(handle); ++closed; return MICROS_OK; }
static micros_result_t digital(micros_context_t *context, micros_handle_t handle, uint32_t *value)
{ (void)context; assert(handle == 1 || handle == 2); *value = handle == 2; return MICROS_OK; }
static micros_result_t analog(micros_context_t *context, micros_handle_t handle, uint32_t *value)
{ (void)context; assert(handle == 1); if (analog_result) return analog_result; *value = 2048; return MICROS_OK; }
micros_result_t monitor_samples_open(const micros_service_args_t *args, micros_handle_t *handle)
{ (void)args; *handle = 9; return MICROS_OK; }
micros_result_t monitor_samples_close(const micros_service_args_t *args, micros_handle_t handle)
{ (void)args; assert(handle == 9); return MICROS_OK; }
micros_result_t monitor_samples_publish(const micros_service_args_t *args, micros_handle_t handle,
                                       const monitor_samples_message_t *message)
{ (void)args; assert(handle == 9 && count < 32); messages[count++] = *message; return MICROS_OK; }

int main(void)
{
    state_t state = {0};
    micros_api_t api = {.monotonic_us = clock_us, .gpio_open = open_pin,
        .gpio_close = close_pin, .gpio_read = digital, .gpio_read_analog = analog};
    micros_service_args_t args = {.arena = &state, .api = &api};
    /* Config default is digital; use the generated encoder identity and values
     * supplied by Python as a binary fixture to exercise real config decoding. */
    FILE *file = fopen(MONITOR_CONFIG_FILE, "rb");
    assert(file);
    uint8_t config[256]; size_t bytes = fread(config, 1, sizeof(config), file); fclose(file);
    args.config_data = config; args.config_bytes = (uint32_t)bytes;
    assert(!initialize(&args));
    assert(opened == 2 && state.config.analog_mask == 2);
    assert(!start(&args));
    assert(!step(&args));
    assert(count == 2 && messages[0].pin == 27 && messages[0].value == 1 && !messages[0].analog);
    assert(messages[1].pin == 34 && messages[1].value == 2048 && messages[1].analog);
    assert(messages[0].sequence == messages[1].sequence && messages[0].sequence == 1);
    assert(messages[0].monotonic_us == now && messages[0].publisher_started_us == 1000);
    assert(!step(&args) && count == 2);
    now += 500000; /* Five late periods produce exactly one scan. */
    analog_result = MICROS_ERROR_BUSY;
    assert(!step(&args) && count == 4);
    assert(messages[3].error == MICROS_ERROR_BUSY && messages[3].value == 0);
    assert(!step(&args) && count == 4);
    state.sequence = UINT32_MAX; now += 100000;
    assert(!step(&args) && messages[4].sequence == 1 && messages[4].publisher_started_us == now);
    assert(!stop(&args) && closed == 2);
    assert(!stop(&args) && closed == 2);
    state = (state_t){0}; opened = closed = 0; fail_line = 0;
    assert(initialize(&args) == MICROS_ERROR_BUSY && opened == 1);
    assert(!stop(&args) && closed == 1);
    fail_line = UINT32_MAX; state = (state_t){0}; analog_result = MICROS_ERROR_UNSUPPORTED;
    assert(initialize(&args) == MICROS_ERROR_UNSUPPORTED);
    assert(!stop(&args));
    /* Selecting the digital-only GPIO as analog fails before any acquisition. */
    config[bytes - 4] = 1;
    opened = 0; state = (state_t){0};
    assert(initialize(&args) == MICROS_ERROR_UNSUPPORTED && opened == 0);
    /* A zero mask reads both pins digitally without using the unsupported ADC. */
    config[bytes - 4] = 0; state = (state_t){0};
    assert(!initialize(&args) && !start(&args));
    unsigned before = count;
    assert(!step(&args) && count == before + 2);
    assert(!messages[before].analog && !messages[before + 1].analog);
    assert(!stop(&args));
    /* Out-of-range mask rejected before acquiring pins. */
    memset(config + bytes - 4, 0, 4);
    config[bytes - 4] = 4; /* Bit 2 lies outside the two declared inputs. */
    opened = 0; state = (state_t){0};
    assert(initialize(&args) != MICROS_OK && opened == 0);
    puts("PASS digital/analog samples, timestamps, cadence, errors, wrap and cleanup");
}
