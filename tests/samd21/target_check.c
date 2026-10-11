#include <stddef.h>
#include <micros/service.h>

/* These checks run under the real cross compiler, not simulated host defines. */
_Static_assert(MICROS_BUILD_TARGET == MICROS_TARGET_ARMV6M, "ARMv6-M target detection");
_Static_assert(MICROS_TARGET_ARMV6M == 5, "native profile identifier");
_Static_assert(sizeof(void *) == 4, "32-bit native pointers");
_Static_assert(sizeof(micros_service_descriptor_t) == 48, "ARM descriptor layout");
_Static_assert(offsetof(micros_service_descriptor_t, init) == 32, "ARM hook offset");
_Static_assert(sizeof(micros_api_t) == 56, "ARM revision 6 callback table layout");
_Static_assert(_Alignof(uint64_t) == 8, "AAPCS 64-bit alignment");
