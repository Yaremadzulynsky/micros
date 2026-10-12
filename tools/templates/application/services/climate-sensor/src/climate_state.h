#ifndef CLIMATE_STATE_H
#define CLIMATE_STATE_H
#include "simulated_sensor.h"
typedef struct { simulated_sensor_t sensor; uint32_t sequence; } climate_state_t;
#endif
