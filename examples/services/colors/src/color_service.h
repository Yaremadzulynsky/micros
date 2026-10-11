#ifndef MICROS_COLOR_SERVICE_H
#define MICROS_COLOR_SERVICE_H
#include "button_input.h"
#include "palette.h"
#include "../drivers/neopixel.h"

/* One bounded decode/24-bit write; native runtime minimum worker stack. */
#define COLOR_SERVICE_STACK_BYTES 4096u

/** @brief Per-instance input, selected color and owned pixel handles. */
typedef struct {
    button_input_t button;
    palette_t palette;
    colors_config_t config;
    neopixel_t pixel;
    uint64_t last_report_us;
} color_service_t;
#endif
