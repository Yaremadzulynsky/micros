#ifndef DISPLAY_STATE_H
#define DISPLAY_STATE_H
#include <stdbool.h>
#include "display_ipc.h"
typedef struct {
    display_climate_reading_message_t reading;
    display_fan_status_message_t fan;
    bool have_reading, have_fan, dirty, stale;
} display_state_t;
#endif
