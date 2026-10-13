#ifndef MICROS_FEATHER_NEOPIXEL_H
#define MICROS_FEATHER_NEOPIXEL_H
#include <stdbool.h>
#include <stdint.h>
#include <micros/service.h>
/** @brief Runtime-owned data and power GPIO handles for a generated pixel binding. */
typedef struct {
    micros_handle_t data_handle, power_handle;
    bool acquired;
} neopixel_t;
micros_result_t neopixel_open(const micros_service_args_t *args, neopixel_t *pixel);
void neopixel_show(uint8_t red, uint8_t green, uint8_t blue);
void neopixel_close(const micros_service_args_t *args, neopixel_t *pixel);
#endif
