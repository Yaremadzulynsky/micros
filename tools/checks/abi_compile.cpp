#include <cstddef>
#include <type_traits>
#include <micros/service.h>

static_assert(std::is_standard_layout<micros_service_descriptor_t>::value, "C-compatible layout");
static_assert(std::is_same<decltype(&micros_service_query), const micros_service_descriptor_t *(*)(void)>::value, "query signature");
static_assert(offsetof(micros_service_descriptor_t, init) == 32, "descriptor prefix");
static_assert(sizeof(micros_service_descriptor_t) == 32 + 4 * sizeof(micros_service_hook_t), "descriptor layout");

/* Revision 2 appends six resource callbacks after the two M1 callbacks. */
static_assert(offsetof(micros_api_t, timer_open) == 16 + 2 * sizeof(void (*)(void)), "resource API prefix");
static_assert(sizeof(micros_api_t) == 16 + 9 * sizeof(void (*)(void)) + sizeof(void *), "revision 6 API layout");
