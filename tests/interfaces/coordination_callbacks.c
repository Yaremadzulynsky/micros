#include "generated/demo_ipc.h"
#include <micros/ipc.h>
#include <assert.h>
#include <string.h>

typedef struct {
    uint64_t revision;
    unsigned ready, status, value;
} record_t;
typedef struct {
    record_t records[7];
    unsigned opened, closed, fail_key, requests, completions;
} backend_t;
typedef struct {
    unsigned starts, steps, stops, finished, changed, events, requests, chain;
    micros_result_t callback_error, stop_error;
    micros_action_t action;
} application_t;

static micros_result_t open_port(micros_context_t *ctx, uint32_t key,
    uint32_t access, uint32_t kind, micros_handle_t *handle)
{
    backend_t *backend = (void *)ctx;
    (void)access; (void)kind;
    if (key == backend->fail_key) return MICROS_ERROR_CAPACITY;
    ++backend->opened;
    *handle = key;
    return MICROS_OK;
}
static micros_result_t close_port(micros_context_t *ctx, micros_handle_t handle)
{
    backend_t *backend = (void *)ctx;
    assert(handle > 0 && handle <= 6);
    ++backend->closed;
    return MICROS_OK;
}
static micros_result_t exchange(micros_context_t *ctx, micros_handle_t handle,
    uint32_t op, uint8_t *data, uint32_t capacity, uint32_t *bytes, micros_coord_info_t *info)
{
    backend_t *backend = (void *)ctx;
    record_t *record = &backend->records[handle];
    assert(capacity >= 2);
    if (op == MICROS_COORD_REQUEST) {
        ++backend->requests;
        ++record->revision;
        record->status = 0;
        *info = (micros_coord_info_t){.generation = 9, .revision = record->revision};
    } else if (op == MICROS_COORD_COMPLETE) {
        assert(handle == 4 && info->generation == 9 && info->revision == record->revision);
        assert(info->status == MICROS_COORD_COMPLETED);
        ++backend->completions;
    } else if (op == MICROS_COORD_SET || op == MICROS_COORD_EMIT) {
        assert(*bytes == 2 && data[0] == 8);
    } else {
        if (op == MICROS_COORD_RESULT ? !record->status : !record->ready)
            return MICROS_ERROR_EMPTY;
        record->ready = 0;
        *info = (micros_coord_info_t){.generation = 9, .revision = record->revision,
                                    .status = record->status};
        data[0] = 8; data[1] = (uint8_t)record->value; *bytes = 2;
    }
    return MICROS_OK;
}
static micros_result_t on_finished(const micros_service_args_t *args, const demo_command_result_t *result)
{
    application_t *app = args->arena;
    assert(result->status == MICROS_COORD_COMPLETED && result->message.value == 73);
    ++app->finished;
    if (app->chain) {
        app->chain = 0;
        demo_command_message_t next = {.value = 99};
        assert(!demo_request_command(args, &next));
    }
    return app->callback_error;
}
static micros_result_t on_changed(const micros_service_args_t *args,
    const demo_observed_message_t *message, const micros_coord_info_t *info)
{
    application_t *app = args->arena;
    assert(message->value == 73 && info->revision == 5);
    ++app->changed;
    return app->callback_error;
}
static micros_result_t on_event(const micros_service_args_t *args,
    const demo_event_in_message_t *message, const micros_coord_info_t *info)
{
    application_t *app = args->arena;
    assert(message->value == 73 && info->revision == 8); /* Gaps remain visible. */
    ++app->events;
    return app->callback_error;
}
static micros_result_t on_request(const micros_service_args_t *args,
    const demo_execute_message_t *request, micros_action_t action)
{
    application_t *app = args->arena;
    assert(request->value == 73);
    ++app->requests;
    app->action = action; /* Deferred completion, after this callback returns. */
    return app->callback_error;
}
static micros_result_t start(const micros_service_args_t *args)
{
    application_t *app = args->arena;
    ++app->starts;
    demo_target_message_t target = {.value = 73};
    demo_event_out_message_t event = {.value = 73};
    assert(!demo_set_target(args, &target));
    return demo_emit_event_out(args, &event);
}
static micros_result_t step(const micros_service_args_t *args)
{
    ++((application_t *)args->arena)->steps;
    return MICROS_OK;
}
static micros_result_t stop(const micros_service_args_t *args)
{
    application_t *app = args->arena;
    ++app->stops;
    return app->stop_error;
}
static const demo_callbacks_t callbacks = {
    .on_command_finished = on_finished, .on_execute_requested = on_request,
    .on_observed_changed = on_changed, .on_event_in_event = on_event,
};
static const micros_service_hooks_t hooks = {.start = start, .step = step, .stop = stop};
DEMO_SERVICE(application_t, 2048, hooks, callbacks)

int main(void)
{
    const struct micros_ipc_api ipc = {.coord_open = open_port, .ipc_close = close_port, .coord = exchange};
    const micros_api_t api = {._ipc = &ipc};
    backend_t backend = {0};
    demo_service_storage_t storage = {0};
    micros_service_args_t args = {.api = &api, .context = (void *)&backend, .arena = &storage};
    application_t *app = &storage.application;
    assert(micros_descriptor.arena_bytes == sizeof(storage));
    assert(micros_descriptor.arena_alignment == _Alignof(demo_service_storage_t));
    assert(!micros_descriptor.init(&args) && backend.opened == 6);
    assert(!micros_descriptor.start(&args) && app->starts == 1);
    demo_command_message_t request = {.value = 73};
    assert(!demo_request_command(&args, &request));
    assert(demo_request_command(&args, &request) == MICROS_ERROR_STATE);
    assert(backend.requests == 1);
    assert(!micros_descriptor.step(&args) && app->finished == 0);
    backend.records[3].status = MICROS_COORD_ACCEPTED;
    assert(!micros_descriptor.step(&args) && app->finished == 0);
    backend.records[3].status = MICROS_COORD_COMPLETED;
    backend.records[3].value = 73;
    assert(!micros_descriptor.step(&args) && app->finished == 1);
    assert(!micros_descriptor.step(&args) && app->finished == 1); /* Retained result. */
    assert(!demo_request_command(&args, &request));
    backend.records[3].status = MICROS_COORD_COMPLETED;
    --backend.records[3].revision; /* Previous request's result must not dispatch. */
    assert(micros_descriptor.step(&args) == MICROS_ERROR_STATE && app->finished == 1);
    ++backend.records[3].revision;
    app->chain = 1;
    assert(!micros_descriptor.step(&args) && app->finished == 2);
    assert(backend.requests == 3); /* Completion callback may submit the next request. */
    backend.records[3].status = MICROS_COORD_COMPLETED;
    app->callback_error = MICROS_ERROR_INVALID_ARGUMENT;
    assert(micros_descriptor.step(&args) == MICROS_ERROR_INVALID_ARGUMENT);
    app->callback_error = 0;
    assert(!micros_descriptor.step(&args) && app->finished == 3);
    backend.records[2] = (record_t){.ready = 1, .revision = 5, .value = 73};
    backend.records[6] = (record_t){.ready = 1, .revision = 8, .value = 73};
    backend.records[4] = (record_t){.ready = 1, .revision = 41, .value = 73};
    assert(!micros_descriptor.step(&args));
    assert(app->changed == 1 && app->events == 1 && app->requests == 1);
    assert(!micros_descriptor.step(&args));
    assert(app->changed == 1 && app->events == 1 && app->requests == 1);
    demo_execute_message_t result = {.value = 73};
    micros_action_t wrong = app->action; wrong._port = 1;
    assert(demo_complete_execute(&args, wrong, MICROS_COORD_COMPLETED, &result) == MICROS_ERROR_STALE_HANDLE);
    assert(!demo_complete_execute(&args, app->action, MICROS_COORD_COMPLETED, &result));
    assert(backend.completions == 1);
    assert(!demo_request_command(&args, &request));
    app->stop_error = MICROS_ERROR_STATE;
    assert(micros_descriptor.stop(&args) == MICROS_ERROR_STATE && backend.closed == 6);
    assert(demo_request_command(&args, &request) == MICROS_ERROR_STATE);
    assert(micros_descriptor.step(&args) == MICROS_ERROR_STATE);

    /* A new instance has no shared adapter state and cleans partial acquisition. */
    backend_t second = {.fail_key = 3};
    demo_service_storage_t second_storage = {0};
    args.context = (void *)&second; args.arena = &second_storage;
    assert(micros_descriptor.init(&args) == MICROS_ERROR_CAPACITY);
    assert(second.opened == 2 && second.closed == 2);
    assert(!micros_descriptor.stop(&args) && second.closed == 2);
    second.fail_key = 0;
    demo_callbacks_t missing = callbacks; missing.on_command_finished = NULL;
    assert(demo_coordination_open(&args, &missing) == MICROS_ERROR_INVALID_ARGUMENT);
    assert(second.opened == 2);
    assert(!micros_descriptor.init(&args));
    assert(!demo_request_command(&args, &request));
    assert(second.requests == 1 && backend.requests == 4);
    assert(!micros_descriptor.stop(&args));
    return 0;
}
