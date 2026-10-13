#include "../generated/probe_config.h"
#include "../generated/probe_ipc.h"

typedef struct {
    probe_config_t config;
    micros_handle_t input, report;
    probe_report_message_t result;
    uint64_t report_due;
    bool final_sent;
} state_t;

static micros_result_t initialize(const micros_service_args_t *a)
{
    state_t *s = a->arena;
    micros_result_t r = probe_config_decode(a->config_data, a->config_bytes, &s->config);
    if (!r) r = probe_input_open(a, &s->input);
    if (!r) r = probe_report_open(a, &s->report);
    return r;
}
static micros_result_t start(const micros_service_args_t *a)
{
    state_t *s = a->arena;
    s->result = (probe_report_message_t){.run_id = s->config.run_id,
        .started_us = a->api->monotonic_us(a->context)};
    s->report_due = s->result.started_us;
    s->final_sent = false;
    return MICROS_OK;
}
static micros_result_t step(const micros_service_args_t *a)
{
    state_t *s = a->arena;
    if (s->final_sent) return MICROS_OK;
    uint64_t now = a->api->monotonic_us(a->context);
    uint64_t end = s->result.started_us + (uint64_t)s->config.duration_ms * 1000u;
    uint64_t observed = now < end ? now : end;
    uint64_t last = s->result.messages ? s->result.last_received_us : s->result.started_us;
    if (observed - last > s->result.max_silence_us) s->result.max_silence_us = observed - last;
    if (now >= end) { s->result.done = true; s->result.reason = 1; }
    for (unsigned n = 0; !s->result.done && n < s->config.reads_per_step; ++n) {
        probe_input_message_t value;
        micros_result_t r = probe_input_read(a, s->input, &value);
        if (r == MICROS_ERROR_EMPTY) { ++s->result.empty_reads; break; }
        if (r == MICROS_ERROR_MESSAGES_MISSED) { ++s->result.missed_events; continue; }
        if (r == MICROS_ERROR_INVALID_ARGUMENT) {
            ++s->result.decode_errors; s->result.last_error = r; continue;
        }
        if (r) { s->result.last_error = r; s->result.done = true; s->result.reason = 3; break; }
        if (!s->result.messages) s->result.first_received_us = now;
        ++s->result.messages;
        s->result.last_received_us = now;
        if (s->result.messages >= s->config.max_messages) {
            s->result.done = true; s->result.reason = 2;
        }
    }
    s->result.observed_us = observed;
    if (s->result.done || now >= s->report_due) {
        micros_result_t r = probe_report_publish(a, s->report, &s->result);
        if (r) return r;
        s->report_due = now + (uint64_t)s->config.report_interval_ms * 1000u;
        s->final_sent = s->result.done;
    }
    return MICROS_OK;
}
static micros_result_t stop(const micros_service_args_t *a)
{
    state_t *s = a->arena;
    micros_result_t r = MICROS_OK, closed;
    if (s->input) { r = probe_input_close(a, s->input); if (!r) s->input = 0; }
    if (s->report) { closed = probe_report_close(a, s->report); if (!closed) s->report = 0; if (!r) r = closed; }
    return r;
}
const micros_service_descriptor_t micros_descriptor = {
    .struct_bytes = sizeof(micros_service_descriptor_t), .abi_major = MICROS_ABI_MAJOR,
    .abi_revision = MICROS_ABI_REVISION, .target = MICROS_BUILD_TARGET,
    .arena_bytes = sizeof(state_t), .arena_alignment = _Alignof(state_t), .stack_bytes = 4096,
    .init = initialize, .start = start, .step = step, .stop = stop,
};
const micros_service_descriptor_t *micros_service_query(void) { return &micros_descriptor; }
