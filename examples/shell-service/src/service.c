#include "shell_demo_ipc.h"

typedef struct {
    micros_handle_t set, status;
    shell_demo_status_message_t observed;
    uint64_t due;
} state_t;

static micros_result_t initialize(const micros_service_args_t *a)
{
    state_t *s = a->arena;
    micros_result_t r = shell_demo_set_open(a, &s->set);
    if (!r) r = shell_demo_status_open(a, &s->status);
    return r;
}
static micros_result_t start(const micros_service_args_t *a)
{
    state_t *s = a->arena;
    s->due = 0;
    return MICROS_OK;
}
static micros_result_t step(const micros_service_args_t *a)
{
    state_t *s = a->arena;
    shell_demo_set_message_t command;
    micros_result_t r = shell_demo_set_read(a, s->set, &command);
    bool changed = r != MICROS_ERROR_EMPTY;
    /* One request per scheduler step bounds work, even when the sender floods. */
    if (!r) {
        if (command.value <= 100) { s->observed.value = command.value; ++s->observed.accepted; }
        else ++s->observed.rejected;
    } else if (r == MICROS_ERROR_MESSAGES_MISSED) ++s->observed.gaps;
    else if (r == MICROS_ERROR_INVALID_ARGUMENT) ++s->observed.rejected;
    else if (r != MICROS_ERROR_EMPTY) return r;
    uint64_t now = a->api->monotonic_us(a->context);
    if (changed || now >= s->due) {
        s->observed.monotonic_us = now;
        r = shell_demo_status_publish(a, s->status, &s->observed);
        if (r) return r;
        s->due = now + UINT64_C(1000000);
    }
    return MICROS_OK;
}
static micros_result_t stop(const micros_service_args_t *a)
{
    state_t *s = a->arena;
    micros_result_t result = MICROS_OK, r;
    if (s->set) { r = shell_demo_set_close(a, s->set); if (!r) s->set = 0; if (!result) result = r; }
    if (s->status) { r = shell_demo_status_close(a, s->status); if (!r) s->status = 0; if (!result) result = r; }
    return result;
}
const micros_service_descriptor_t micros_descriptor = {
    .struct_bytes = sizeof(micros_service_descriptor_t), .abi_major = MICROS_ABI_MAJOR,
    .abi_revision = MICROS_ABI_REVISION, .target = MICROS_BUILD_TARGET,
    .arena_bytes = sizeof(state_t), .arena_alignment = _Alignof(state_t), .stack_bytes = 2048,
    .init = initialize, .start = start, .step = step, .stop = stop,
};
const micros_service_descriptor_t *micros_service_query(void) { return &micros_descriptor; }
