#ifndef SIMULATED_SENSOR_H
#define SIMULATED_SENSOR_H
#include <stdint.h>
typedef struct { uint32_t phase; } simulated_sensor_t;
typedef struct { int32_t temperature_millicelsius; uint32_t humidity_permille; } simulated_sample_t;
/* Deterministic driver: no GPIO, randomness, network or external input. */
void simulated_sensor_reset(simulated_sensor_t *sensor);
simulated_sample_t simulated_sensor_read(simulated_sensor_t *sensor);
#endif
