#include "../generated/probe_resources.h"

/** @brief Acquire the deployment-selected output and drive it high for readback. */
static micros_result_t initialize(const micros_service_args_t *args)
{
    micros_handle_t *output = args->arena;
    micros_result_t result = probe_test_output_open(args, output);
    return result ? result : args->api->gpio_write(args->context, *output, 1);
}

static micros_result_t idle(const micros_service_args_t *args)
{
    (void)args;
    return MICROS_OK;
}

static micros_result_t stop(const micros_service_args_t *args)
{
    micros_handle_t *output = args->arena;
    if (!*output)
        return MICROS_OK;
    micros_result_t result = args->api->gpio_write(args->context, *output, 0);
    micros_result_t close_result = args->api->gpio_close(args->context, *output);
    return result ? result : close_result;
}

/** @brief Hardware test fixture; no fixed pin or board-specific register access. */
const micros_service_descriptor_t micros_descriptor = {
    .struct_bytes = sizeof(micros_service_descriptor_t),
    .abi_major = MICROS_ABI_MAJOR,
    .abi_revision = MICROS_ABI_REVISION,
    .target = MICROS_BUILD_TARGET,
    .arena_bytes = sizeof(micros_handle_t),
    .arena_alignment = _Alignof(micros_handle_t),
    .stack_bytes = 4096, /* Default worker stack. */
    .init = initialize,
    .start = idle,
    .step = idle,
    .stop = stop,
};

const micros_service_descriptor_t *micros_service_query(void)
{
    return &micros_descriptor;
}
