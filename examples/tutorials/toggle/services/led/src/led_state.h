#ifndef LED_STATE_H
#define LED_STATE_H
#include <stdint.h>
typedef struct {
    uint64_t started_us;
    uint32_t level;
} led_state_t;
#endif
