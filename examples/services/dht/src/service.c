#include "dht_resources.h"
#include <micros/service.h>
#include "dht_ipc.h"

/* ESP32-only OTA driver. The input grant leaves the external ~5k pull-up in
 * control. Enable the output only with its latch LOW; never drive the bus HIGH.
 * GPIO mux/input setup is supplied by the base's graph binding. */
#define PIN DHT_DHT_DATA_GPIO_PIN
_Static_assert(PIN == 27, "Diagnostic is validated for Feather GPIO27 only");
#define MASK (UINT32_C(1) << PIN)
#define REG(offset) (*(volatile uint32_t *)(uintptr_t)(0x3ff44000u + (offset)))
#define CYCLES_PER_US 160u

typedef struct {
    micros_handle_t gpio;
    micros_handle_t channel;
    uint32_t sequence;
    uint64_t publisher_started_us;
    int routing_saved;
    uint64_t due;
    int requesting;
    uint32_t saved_output_route;
} state_t;
static inline __attribute__((always_inline)) uint32_t cycles(void)
{
    uint32_t value;
    __asm__ volatile("rsr.ccount %0" : "=a"(value));
    return value;
}
static int level(void) { return (REG(0x3c) & MASK) != 0; }
static void release(void) { REG(0x28) = MASK; }
static int pulse(int expected, unsigned timeout)
{
    uint32_t start = cycles(), elapsed;
    do {
        elapsed = cycles() - start;
        if (elapsed >= timeout * CYCLES_PER_US) return -1;
    } while (level() == expected);
    return (int)(elapsed / CYCLES_PER_US);
}
static const char *receive(uint8_t data[5])
{
    const char *error = 0;
    uint32_t ps;
    __asm__ volatile("rsil %0, 5" : "=a"(ps) :: "memory");
    release();
    uint32_t start = cycles();
    while ((uint32_t)(cycles() - start) < 5 * CYCLES_PER_US) {}
    if (pulse(1, 120) < 0) error = "no response (check power/data/sensor)";
    else if (pulse(0, 120) < 0) error = "response stuck LOW";
    else if (pulse(1, 120) < 0) error = "response stuck HIGH";
    else for (unsigned bit = 0; bit < 40; ++bit) {
        if (pulse(0, 100) < 0) { error = "data LOW timeout"; break; }
        int high = pulse(1, 120);
        if (high < 0) { error = "data HIGH timeout"; break; }
        data[bit / 8] = (uint8_t)((data[bit / 8] << 1) | (high > 50));
    }
    __asm__ volatile("memw\nwsr.ps %0\nrsync" :: "a"(ps) : "memory");
    if (error) return error;
    if ((uint8_t)(data[0]+data[1]+data[2]+data[3]) != data[4]) return "checksum mismatch";
    if (!(data[0]|data[1]|data[2]|data[3])) return "all-zero frame (not credible indoors)";
    return 0;
}
static char *append(char *out, const char *text)
{
    while (*text) *out++ = *text++;
    return out;
}
static char *number(char *out, unsigned value)
{
    if (value >= 100) *out++ = '0' + value / 100;
    if (value >= 10) *out++ = '0' + value / 10 % 10;
    *out++ = '0' + value % 10;
    return out;
}
static micros_result_t report(const micros_service_args_t *args, const char *error, uint8_t data[5])
{
    state_t *s = args->arena;
    uint64_t now = args->api->monotonic_us(args->context);
    if (s->sequence == UINT32_MAX) {
        s->sequence = 0;
        s->publisher_started_us = now ? now : 1;
    }
    dht_environment_message_t message = {
        .sequence = ++s->sequence,
        .monotonic_us = now,
        .publisher_started_us = s->publisher_started_us,
        .valid = error == 0,
    };
    if (!error) {
        message.temperature_tenths_c = data[2] * 10 + (data[3] & 0x7f);
        if (data[3] & 0x80) message.temperature_tenths_c = -message.temperature_tenths_c;
        message.humidity_tenths_percent = data[0] * 10 + data[1];
    }
    micros_result_t result = dht_environment_publish(args, s->channel, &message);
    if (result) return result;
    char text[200], *p = append(text, "DHT11 GPIO27: ");
    if (error) p = append(p, error);
    else {
        p = append(p, "OK temperature=");
        if (data[3] & 0x80) *p++ = '-';
        p = number(p, data[2]); *p++ = '.'; p = number(p, data[3] & 0x7f);
        p = append(p, " C humidity=");
        p = number(p, data[0]); *p++ = '.'; p = number(p, data[1]);
        p = append(p, " % RH");
    }
    p = append(p, " raw=");
    const char *hex = "0123456789abcdef";
    for (unsigned i = 0; i < 5; ++i) {
        *p++ = hex[data[i] >> 4]; *p++ = hex[data[i] & 15]; *p++ = ' ';
    }
    *p++ = '\n';
    return args->api->debug_write(args->context, (const uint8_t *)text, (uint32_t)(p-text));
}
static micros_result_t initialize(const micros_service_args_t *args)
{
    state_t *s = args->arena;
    micros_result_t result = dht_dht_data_open(args, &s->gpio);
    return result ? result : dht_environment_open(args, &s->channel);
}
static micros_result_t start(const micros_service_args_t *args)
{
    state_t *s = args->arena;
    release();
    REG(0x0c) = MASK;
    s->saved_output_route = REG(0x59c);
    s->routing_saved = 1;
    s->sequence = 0;
    s->publisher_started_us = args->api->monotonic_us(args->context);
    if (!s->publisher_started_us) s->publisher_started_us = 1;
    REG(0x59c) = 256u | (1u << 10); /* GPIO latch, software output enable. */
    s->requesting = 0;
    s->due = args->api->monotonic_us(args->context) + 2000000;
    return MICROS_OK;
}
static micros_result_t step(const micros_service_args_t *args)
{
    state_t *s = args->arena;
    uint64_t now = args->api->monotonic_us(args->context);
    if (now < s->due) return MICROS_OK;
    uint8_t data[5] = {0};
    if (!s->requesting) {
        if (!level()) {
            s->due = now + 2500000;
            return report(args, "DATA stuck LOW (check wiring/short)", data);
        }
        REG(0x0c) = MASK;
        REG(0x24) = MASK;
        s->requesting = 1;
        s->due = now + 20000;
        return MICROS_OK;
    }
    const char *error = receive(data);
    s->requesting = 0;
    s->due = args->api->monotonic_us(args->context) + 2500000;
    return report(args, error, data);
}
static micros_result_t stop(const micros_service_args_t *args)
{
    state_t *s = args->arena;
    micros_result_t result = MICROS_OK;
    if (s->gpio) {
        release();
        if (s->routing_saved) REG(0x59c) = s->saved_output_route;
        result = args->api->gpio_close(args->context, s->gpio);
    }
    if (s->channel) {
        micros_result_t closed = dht_environment_close(args, s->channel);
        if (!result) result = closed;
    }
    return result;
}
const micros_service_descriptor_t micros_descriptor = {
    .struct_bytes = sizeof(micros_service_descriptor_t),
    .abi_major = MICROS_ABI_MAJOR, .abi_revision = MICROS_ABI_REVISION,
    .target = MICROS_BUILD_TARGET,
    .arena_bytes = sizeof(state_t), .arena_alignment = _Alignof(state_t),
    .stack_bytes = 4096,
    .init = initialize, .start = start, .step = step, .stop = stop,
};
const micros_service_descriptor_t *micros_service_query(void) { return &micros_descriptor; }
