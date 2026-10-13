#ifndef MICROS_COORDINATION_H
#define MICROS_COORDINATION_H
#include <stdint.h>
/* Runtime-owned opaque identity; application code may copy/compare it, never increment it. */
typedef struct {
    uint64_t generation, revision;
    uint64_t applied_generation, applied_revision;
    uint64_t observation_age_us;
    uint32_t status;
} micros_coord_info_t;
enum { MICROS_COORD_STATE=1, MICROS_COORD_ACTION=2, MICROS_COORD_EVENT=3 };
enum { MICROS_COORD_SET=1, MICROS_COORD_READ=2, MICROS_COORD_REQUEST=3,
       MICROS_COORD_NEXT=4, MICROS_COORD_COMPLETE=5, MICROS_COORD_RESULT=6,
       MICROS_COORD_EMIT=7, MICROS_COORD_RECEIVE=8 };
enum { MICROS_COORD_ACCEPTED=1, MICROS_COORD_COMPLETED=2, MICROS_COORD_FAILED=3,
       MICROS_COORD_REJECTED=4, MICROS_COORD_INDETERMINATE=5 };
#define MICROS_COORD_PAYLOAD 64u
#endif
