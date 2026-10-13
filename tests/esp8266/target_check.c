#include <stddef.h>
#include <micros/service.h>
_Static_assert(MICROS_BUILD_TARGET == MICROS_TARGET_ESP8266_XTENSA, "call0 target detection");
_Static_assert(MICROS_TARGET_ESP8266_XTENSA == 6, "distinct native profile identifier");
_Static_assert(sizeof(void *) == 4, "32-bit pointers");
_Static_assert(sizeof(micros_service_descriptor_t) == 48, "call0 descriptor layout");
_Static_assert(offsetof(micros_service_descriptor_t, init) == 32, "call0 hook offset");
_Static_assert(sizeof(micros_api_t) == 56, "call0 revision 6 callback table layout");
