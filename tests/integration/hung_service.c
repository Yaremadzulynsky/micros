#include <micros/service.h>
static micros_result_t uncooperative_hook(const micros_service_args_t *service_args)
{
    (void)service_args;
    for (;;) { /* Deliberate timeout fixture. */
    }
    return MICROS_OK;
}
const micros_service_descriptor_t *micros_service_query(void)
{
    /* No arena state is used. Eight-byte alignment and a 4 KiB stack match
     * the ordinary demo; the only deliberate difference is a non-returning hook. */
    static const micros_service_descriptor_t descriptor = {
        .struct_bytes = sizeof(descriptor),
        .abi_major = MICROS_ABI_MAJOR,
        .abi_revision = MICROS_ABI_REVISION,
        .target = MICROS_BUILD_TARGET,
        .arena_bytes = 0,
        .arena_alignment = 8,
        .stack_bytes = 4096,
        .reserved = 0,
        .init = uncooperative_hook,
        .start = uncooperative_hook,
        .step = uncooperative_hook,
        .stop = uncooperative_hook,
    };
    return &descriptor;
}
