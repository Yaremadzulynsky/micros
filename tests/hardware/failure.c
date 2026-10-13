#include <micros/service.h>
/** @brief Deliberate failed-start candidate for base-owned boot rollback validation. */
static micros_result_t okay(const micros_service_args_t *args)
{
    (void)args;
    return MICROS_OK;
}
static micros_result_t fail_start(const micros_service_args_t *args)
{
    (void)args;
    return MICROS_ERROR_SERVICE;
}
/** @brief Matches the button fixture's declared memory while rejecting its start transition. */
static const micros_service_descriptor_t descriptor = {
    .struct_bytes = sizeof(micros_service_descriptor_t),
    .abi_major = MICROS_ABI_MAJOR,
    .abi_revision = MICROS_ABI_REVISION,
    .target = MICROS_SERVICE_TARGET,
    .arena_bytes = 40,    /* The normal button fixture has five padded 64-bit arena fields. */
    .arena_alignment = 8, /* uint64_t state alignment in the selected native profile. */
    .stack_bytes = 4096,  /* Same admitted worker stack as the normal board demo. */
    .init = okay,
    .start = fail_start,
    .step = okay,
    .stop = okay};
const micros_service_descriptor_t *micros_service_query(void)
{
    return &descriptor;
}
