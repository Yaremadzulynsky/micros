#include <micros/service.h>
static micros_result_t okay(const micros_service_args_t *args)
{
    (void)args;
    return MICROS_OK;
}
static micros_result_t hang(const micros_service_args_t *args)
{
    (void)args;
    for (;;)
    {
        __asm__ volatile("" ::: "memory");
    }
}
static const micros_service_descriptor_t micros_descriptor = {
    .struct_bytes = sizeof(micros_service_descriptor_t),
    .abi_major = MICROS_ABI_MAJOR,
    .abi_revision = MICROS_ABI_REVISION,
    .target = MICROS_BUILD_TARGET,
    .arena_bytes = 8,
    .arena_alignment = 4,
    .stack_bytes = 1024,
    .init = okay,
    .start = okay,
    .step = hang,
    .stop = okay};
const micros_service_descriptor_t *micros_service_query(void) { return &micros_descriptor; }
