#include "simulated_sensor.h"
void simulated_sensor_reset(simulated_sensor_t *sensor) { sensor->phase = 0; }
simulated_sample_t simulated_sensor_read(simulated_sensor_t *sensor)
{
    uint32_t step = sensor->phase <= 5 ? sensor->phase : 10 - sensor->phase;
    simulated_sample_t sample = {20000 + (int32_t)step * 2000, 450 + step * 10};
    sensor->phase = (sensor->phase + 1) % 10;
    return sample;
}
