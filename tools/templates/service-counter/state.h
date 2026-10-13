#ifndef COUNTER_STATE_H
#define COUNTER_STATE_H
#include <stdint.h>
/* Micros creates a separate, zeroed state for each service instance. */
typedef struct { uint32_t count; } counter_state_t;
#endif
