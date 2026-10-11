#include "../generated/console_ipc.h"

/* The resident authenticated transport reads/writes these owned ports under the
 * runtime lock. There is no second queue, socket, codec or worker here. */
_Static_assert(CONSOLE_IPC_PORT_COUNT > 0, "Declare at least one bridge port");
typedef struct {
    micros_handle_t ports[CONSOLE_IPC_PORT_COUNT];
} state_t;

static micros_result_t initialize(const micros_service_args_t *args)
{
    state_t *state = args->arena;
    micros_result_t result = MICROS_OK;
#define OPEN(index, port) \
    if (!result) result = port##_open(args, &state->ports[index]);
    CONSOLE_IPC_PORTS(OPEN)
#undef OPEN
    return result;
}

static micros_result_t idle(const micros_service_args_t *args)
{
    (void)args;
    return MICROS_OK;
}

static micros_result_t stop(const micros_service_args_t *args)
{
    state_t *state = args->arena;
    micros_result_t result = MICROS_OK;
#define CLOSE(index, port) \
    if (state->ports[index]) { \
        micros_result_t closed = port##_close(args, state->ports[index]); \
        if (!closed) state->ports[index] = 0; \
        if (!result) result = closed; \
    }
    CONSOLE_IPC_PORTS(CLOSE)
#undef CLOSE
    return result;
}

const micros_service_descriptor_t micros_descriptor = {
    .struct_bytes = sizeof(micros_service_descriptor_t),
    .abi_major = MICROS_ABI_MAJOR, .abi_revision = MICROS_ABI_REVISION,
    .target = MICROS_BUILD_TARGET,
    .arena_bytes = sizeof(state_t), .arena_alignment = _Alignof(state_t),
    .stack_bytes = 2048,
    .init = initialize, .start = idle, .step = idle, .stop = stop,
};
const micros_service_descriptor_t *micros_service_query(void) { return &micros_descriptor; }
