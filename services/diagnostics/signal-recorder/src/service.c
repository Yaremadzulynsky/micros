#include "../generated/recorder_config.h"
#include "../generated/recorder_resources.h"
#include "../generated/recorder_ipc.h"

_Static_assert(RECORDER_GPIO_COUNT == 1, "Recorder owns exactly one input");
#define INPUT_ONLY(index, prefix, pin, output) _Static_assert(!output, "Recorder requires an input GPIO");
RECORDER_GPIO_PINS(INPUT_ONLY)
#undef INPUT_ONLY
#define PIN(index, prefix, pin, output) pin,
static const uint32_t pins[] = {RECORDER_GPIO_PINS(PIN)};
#undef PIN
#define CAPACITY 32u

typedef struct {
    recorder_config_t config;
    micros_handle_t gpio, records, status;
    micros_diagnostics_v1_CaptureRecord_Sample ring[CAPACITY];
    recorder_status_message_t result;
    uint64_t due;
    uint32_t head, post, previous;
    bool previous_valid, dirty;
} state_t;
static micros_result_t initialize(const micros_service_args_t *a)
{
    state_t *s = a->arena;
    micros_result_t r = recorder_config_decode(a->config_data, a->config_bytes, &s->config);
    if (r) return r;
    if (s->config.pre_samples + s->config.post_samples + 1 > CAPACITY) return MICROS_ERROR_CAPACITY;
    if (s->config.analog && (s->config.trigger == 1 || s->config.trigger == 2)) return MICROS_ERROR_INVALID_ARGUMENT;
    if (!s->config.analog && s->config.trigger >= 3 && s->config.threshold > 1) return MICROS_ERROR_INVALID_ARGUMENT;
    if (s->config.analog && (pins[0] < 32 || pins[0] > 39 || !a->api->gpio_read_analog)) return MICROS_ERROR_UNSUPPORTED;
#define OPEN(index, prefix, pin, output) r = prefix##_open(a, &s->gpio);
    RECORDER_GPIO_PINS(OPEN)
#undef OPEN
    if (!r && s->config.analog) {
        uint32_t ignored;
        r = a->api->gpio_read_analog(a->context, s->gpio, &ignored);
        if (r == MICROS_ERROR_BUSY) r = MICROS_OK;
    }
    if (!r) r = recorder_records_open(a, &s->records);
    if (!r) r = recorder_status_open(a, &s->status);
    return r;
}
static micros_result_t start(const micros_service_args_t *a)
{
    state_t *s = a->arena;
    s->due = a->api->monotonic_us(a->context);
    s->result = (recorder_status_message_t){.run_id = s->config.run_id, .started_us = s->due};
    s->head = s->post = 0;
    s->previous_valid = false;
    s->dirty = true;
    return MICROS_OK;
}
static bool trigger(state_t *s, const micros_diagnostics_v1_CaptureRecord_Sample *v)
{
    if (v->error) return false;
    switch (s->config.trigger) {
    case 0: return true;
    case 1: return s->previous_valid && !s->previous && v->value != 0;
    case 2: return s->previous_valid && s->previous != 0 && !v->value;
    case 3: return v->value >= s->config.threshold;
    case 4: return v->value <= s->config.threshold;
    default: return false;
    }
}
static micros_result_t step(const micros_service_args_t *a)
{
    state_t *s = a->arena;
    if (s->result.done) return MICROS_OK;
    uint64_t now = a->api->monotonic_us(a->context);
    if (!s->result.reason && now - s->result.started_us >= (uint64_t)s->config.duration_ms * 1000u) {
        s->result.reason = 2; s->dirty = true;
    }
    if (!s->result.reason && now >= s->due) {
        uint64_t period = (uint64_t)s->config.sample_interval_ms * 1000u;
        s->result.skipped_scans += (uint32_t)((now - s->due) / period);
        s->due = now + period;
        micros_diagnostics_v1_CaptureRecord_Sample v = {.pin = pins[0], .analog = s->config.analog,
            .sequence = ++s->result.attempts};
        v.error = v.analog ? a->api->gpio_read_analog(a->context, s->gpio, &v.value)
                          : a->api->gpio_read(a->context, s->gpio, &v.value);
        v.monotonic_us = a->api->monotonic_us(a->context);
        if (v.error) { v.value = 0; ++s->result.read_errors; }
        bool was_triggered = s->result.triggered;
        if (!was_triggered && trigger(s, &v)) {
            s->result.triggered = true; s->result.trigger_us = v.monotonic_us; v.trigger = true;
        }
        s->previous = v.value;
        s->previous_valid = !v.error;
        if (s->result.triggered || s->config.pre_samples) {
            if (!s->result.triggered && s->result.retained == s->config.pre_samples) {
                s->head = (s->head + 1u) % CAPACITY; --s->result.retained;
            }
            s->ring[(s->head + s->result.retained++) % CAPACITY] = v;
        }
        if (was_triggered) ++s->post;
        if (s->result.triggered && s->post == s->config.post_samples) s->result.reason = 1;
        s->dirty = true;
    }
    /* Emit only once capture is frozen: acquisition cannot be slowed by remote viewers. */
    if (s->result.reason) {
        if (s->result.emitted < s->result.retained) {
            recorder_records_message_t v = {.run_id=s->config.run_id,
                .first_index=s->result.emitted, .total=s->result.retained,
                .monotonic_us=s->ring[(s->head+s->result.emitted)%CAPACITY].monotonic_us};
            while (v.samples_count < 4 && s->result.emitted + v.samples_count < s->result.retained) {
                unsigned index = s->result.emitted + v.samples_count;
                v.samples[v.samples_count] = s->ring[(s->head+index)%CAPACITY];
                v.samples[v.samples_count++].index = index;
            }
            micros_result_t r = recorder_records_publish(a, s->records, &v);
            if (r) return r;
            s->result.emitted += v.samples_count;
        }
        s->result.done = s->result.emitted == s->result.retained;
        s->dirty = true;
    }
    if (s->dirty) {
        s->result.observed_us = now;
        micros_result_t r = recorder_status_publish(a, s->status, &s->result);
        if (r) return r;
        s->dirty = false;
    }
    return MICROS_OK;
}
static micros_result_t stop(const micros_service_args_t *a)
{
    state_t *s = a->arena;
    micros_result_t result = MICROS_OK, r;
    if (s->gpio) { r = a->api->gpio_close(a->context, s->gpio); if (!r) s->gpio = 0; if (!result) result = r; }
#define CLOSE(port) if (s->port) { r = recorder_##port##_close(a, s->port); if (!r) s->port = 0; if (!result) result = r; }
    CLOSE(records) CLOSE(status)
#undef CLOSE
    return result;
}
const micros_service_descriptor_t micros_descriptor = {
    .struct_bytes = sizeof(micros_service_descriptor_t), .abi_major = MICROS_ABI_MAJOR,
    .abi_revision = MICROS_ABI_REVISION, .target = MICROS_BUILD_TARGET,
    .arena_bytes = sizeof(state_t), .arena_alignment = _Alignof(state_t), .stack_bytes = 4096,
    .init = initialize, .start = start, .step = step, .stop = stop,
};
const micros_service_descriptor_t *micros_service_query(void) { return &micros_descriptor; }
