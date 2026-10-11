#include "state.h"

static micros_result_t init(const micros_service_args_t *args)
{
    counter_t *state = args->arena;
    return counter_commands_open(args, &state->commands);
}
static micros_result_t start(const micros_service_args_t *args)
{
    (void)args;
    return MICROS_OK;
}
static micros_result_t step(const micros_service_args_t *args)
{
    counter_t *state = args->arena;
    return counter_commands_step(args, &state->commands);
}
static micros_result_t stop(const micros_service_args_t *args)
{
    counter_t *state = args->arena;
    return counter_commands_close(args, &state->commands);
}
const micros_service_descriptor_t micros_descriptor = {
    .struct_bytes = sizeof(micros_service_descriptor_t),
    .abi_major = MICROS_ABI_MAJOR, .abi_revision = MICROS_ABI_REVISION,
    .target = MICROS_SERVICE_TARGET,
    .arena_bytes = sizeof(counter_t), .arena_alignment = _Alignof(counter_t),
    .stack_bytes = 2048,
    .init = init, .start = start, .step = step, .stop = stop,
};
const micros_service_descriptor_t *micros_service_query(void) { return &micros_descriptor; }
