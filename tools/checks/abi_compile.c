#include <stddef.h>
#include <micros/service.h>

_Static_assert(sizeof(micros_result_t) == 4, "result width");
_Static_assert(offsetof(micros_service_descriptor_t, init) == 32, "descriptor prefix");
_Static_assert(offsetof(micros_api_t, debug_write) == 16, "API prefix");
_Static_assert(sizeof(micros_service_descriptor_t) == 32 + 4 * sizeof(micros_service_hook_t), "descriptor layout");

static micros_result_t hook(const micros_service_args_t *args)
{
    if (args == NULL || args->api == NULL) {
        return MICROS_ERROR_INVALID_ARGUMENT;
    }
    return MICROS_OK;
}

/* Compile-only fixture, not a loadable service. */
const micros_service_descriptor_t *micros_service_query(void)
{
    static const micros_service_descriptor_t descriptor = {
        sizeof(micros_service_descriptor_t), MICROS_ABI_MAJOR, MICROS_ABI_REVISION,
        MICROS_TARGET_MACOS_ARM64, 64, 8, 4096, 0,
        hook, hook, hook, hook
    };
    return &descriptor;
}

/* Revision 2 appends six resource callbacks after the two M1 callbacks. */
_Static_assert(offsetof(micros_api_t, timer_open) == 16 + 2 * sizeof(void (*)(void)), "resource API prefix");
_Static_assert(sizeof(micros_api_t) == 16 + 9 * sizeof(void (*)(void)) + sizeof(void *), "revision 6 API layout");
