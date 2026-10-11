#include <colors_config.h>

static micros_result_t initialize(const micros_service_args_t *args)
{
    colors_config_t *config = args->arena;
    micros_result_t result = colors_config_decode(args->config_data, args->config_bytes, config);
    if (result)
        return result;
    /* Test values are single decimal digits; verify delivery without hosted formatting. */
    uint8_t message[] = "brightness=0\n";
    message[sizeof("brightness=") - 1] = (uint8_t)('0' + config->brightness);
    return args->api->debug_write(args->context, message, sizeof(message) - 1);
}
static micros_result_t no_work(const micros_service_args_t *args)
{
    (void)args;
    return MICROS_OK;
}
static const micros_service_descriptor_t descriptor = {
    .struct_bytes = sizeof(micros_service_descriptor_t),
    .abi_major = MICROS_ABI_MAJOR,
    .abi_revision = MICROS_ABI_REVISION,
    .target = MICROS_BUILD_TARGET,
    .arena_bytes = sizeof(colors_config_t),
    .arena_alignment = _Alignof(colors_config_t),
    .stack_bytes = 4096, /* Default worker stack. */
    .init = initialize, .start = no_work, .step = no_work, .stop = no_work,
};
const micros_service_descriptor_t *micros_service_query(void)
{
    return &descriptor;
}
