#include "../generated/replay_config.h"
#include "../generated/replay_ipc.h"

#define FRAME_LIMIT 16u
#define BYTES_LIMIT 48u
#define LOAD 1u
#define START 2u
#define RUNNING 2u
#define COMPLETE 3u
#define FAILED 4u

typedef struct { uint32_t after_ms, bytes; uint8_t data[BYTES_LIMIT]; } frame_t;
typedef struct {
    replay_config_t config;
    micros_handle_t commands, output, status;
    replay_status_message_t result;
    frame_t frames[FRAME_LIMIT];
    uint32_t count;
    uint64_t waiting_since;
    bool dirty;
} state_t;

static micros_result_t initialize(const micros_service_args_t *a)
{
    state_t *s = a->arena;
    micros_result_t r = replay_config_decode(a->config_data, a->config_bytes, &s->config);
    if (!r) r = replay_commands_open(a, &s->commands);
    if (!r) r = replay_output_open(a, &s->output);
    if (!r) r = replay_status_open(a, &s->status);
    return r;
}
static micros_result_t start(const micros_service_args_t *a)
{
    state_t *s = a->arena;
    s->result = (replay_status_message_t){0};
    s->count = 0;
    s->waiting_since = a->api->monotonic_us(a->context);
    s->dirty = true;
    return MICROS_OK;
}
static micros_result_t accept(state_t *s, const replay_commands_message_t *c, uint64_t now)
{
    static const char expected[] = REPLAY_OUTPUT_SCHEMA_SHA256;
    static const char hex[] = "0123456789abcdef";
    if (c->schema_sha256.size != 32) return MICROS_ERROR_INVALID_ARGUMENT;
    for (unsigned i = 0; i < 32; ++i)
        if (hex[c->schema_sha256.bytes[i] >> 4] != expected[2*i] ||
            hex[c->schema_sha256.bytes[i] & 15] != expected[2*i+1]) return MICROS_ERROR_INVALID_ARGUMENT;
    if (!c->run_id || (s->result.run_id && c->run_id != s->result.run_id)) return MICROS_ERROR_STATE;
    if (c->operation == START) {
        if (!s->result.run_id || !c->count || c->count > FRAME_LIMIT || c->payload.size || c->after_ms || c->index)
            return MICROS_ERROR_INVALID_ARGUMENT;
        /* An uncertain START acknowledgement must not cause a second replay. */
        if ((s->result.phase == RUNNING || s->result.phase == COMPLETE) && c->count == s->count) return MICROS_OK;
        if (s->result.phase != 1 || s->result.loaded_mask != ((1u << c->count) - 1u)) return MICROS_ERROR_STATE;
        for (unsigned i = 1; i < c->count; ++i)
            if (s->frames[i].after_ms < s->frames[i-1].after_ms) return MICROS_ERROR_INVALID_ARGUMENT;
        s->count = c->count;
        s->result.started_us = now;
        s->result.phase = RUNNING;
        return MICROS_OK;
    }
    if (c->operation != LOAD || c->index >= FRAME_LIMIT || c->after_ms > s->config.max_duration_ms || c->count)
        return MICROS_ERROR_INVALID_ARGUMENT;
    if (s->result.phase >= RUNNING || c->payload.size > BYTES_LIMIT) return MICROS_ERROR_STATE;
    replay_output_message_t decoded;
    micros_result_t r = replay_output_decode(c->payload.bytes, c->payload.size, &decoded);
    if (r) return r;
    frame_t *f = &s->frames[c->index];
    if (s->result.loaded_mask & (1u << c->index)) {
        if (f->after_ms != c->after_ms || f->bytes != c->payload.size) return MICROS_ERROR_STATE;
        for (unsigned i = 0; i < f->bytes; ++i) if (f->data[i] != c->payload.bytes[i]) return MICROS_ERROR_STATE;
        return MICROS_OK;
    }
    f->after_ms = c->after_ms;
    f->bytes = c->payload.size;
    for (unsigned i = 0; i < f->bytes; ++i) f->data[i] = c->payload.bytes[i];
    s->result.run_id = c->run_id;
    s->result.loaded_mask |= 1u << c->index;
    s->result.phase = 1;
    return MICROS_OK;
}
static micros_result_t step(const micros_service_args_t *a)
{
    state_t *s = a->arena;
    uint64_t now = a->api->monotonic_us(a->context);
    /* Timeout before reading: a command arriving after expiry cannot arm output. */
    if (s->result.phase < RUNNING && now - s->waiting_since >= (uint64_t)s->config.arm_timeout_ms * 1000u) {
        s->result.phase = FAILED; s->result.last_error = MICROS_ERROR_EMPTY; s->dirty = true;
    }
    for (unsigned n = 0; n < 2; ++n) {
        replay_commands_message_t c;
        micros_result_t r = replay_commands_read(a, s->commands, &c);
        if (r == MICROS_ERROR_EMPTY) break;
        if (!r) r = accept(s, &c, now);
        if (r) { ++s->result.rejected_commands; s->result.last_error = r; }
        else s->result.last_error = 0;
        s->dirty = true;
    }
    /* Preserve order, and never perform unbounded catch-up work after a late step. */
    for (unsigned n = 0; s->result.phase == RUNNING && n < 4; ++n) {
        frame_t *f = &s->frames[s->result.published];
        uint64_t due = s->result.started_us + (uint64_t)f->after_ms * 1000u;
        if (now < due) break;
        if (now - due > s->result.max_late_us) s->result.max_late_us = now - due;
        if (now - due > (uint64_t)s->config.max_lateness_ms * 1000u) {
            s->result.phase = FAILED; s->result.last_error = MICROS_ERROR_BUSY;
            s->dirty = true; break;
        }
        replay_output_message_t value;
        micros_result_t r = replay_output_decode(f->data, f->bytes, &value);
        if (!r) r = replay_output_publish(a, s->output, &value);
        if (r) { s->result.last_error = r; s->result.phase = FAILED; }
        else if (++s->result.published == s->count) s->result.phase = COMPLETE;
        s->dirty = true;
    }
    if (s->dirty) {
        s->result.observed_us = now;
        micros_result_t r = replay_status_publish(a, s->status, &s->result);
        if (r) return r;
        s->dirty = false;
    }
    return MICROS_OK;
}
static micros_result_t stop(const micros_service_args_t *a)
{
    state_t *s = a->arena;
    micros_result_t result = MICROS_OK, r;
#define CLOSE(port) if (s->port) { r = replay_##port##_close(a, s->port); if (!r) s->port = 0; if (!result) result = r; }
    CLOSE(commands) CLOSE(output) CLOSE(status)
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
