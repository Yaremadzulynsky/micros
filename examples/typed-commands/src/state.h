#ifndef COUNTER_STATE_H
#define COUNTER_STATE_H
#include "counter_commands.h"
typedef struct {
    counter_commands_t commands;
    uint32_t value;
} counter_t;
#endif
