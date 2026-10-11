#ifndef MICROS_PALETTE_H
#define MICROS_PALETTE_H
#include <micros/service.h>
#include "../generated/colors_config.h"

/** @brief Current color selection; zero initialization selects red. */
typedef struct {
    uint32_t color_index;
    uint8_t brightness;
} palette_t;

/** @brief Set the initial palette selection and brightness from validated configuration. */
void configure_palette(palette_t *palette, const colors_config_t *config);

/** @brief Advance through six hues, dim white and off, wrapping back to red. */
void select_next_color(palette_t *palette);
/** @brief Display the selected RGB color and write its diagnostic name. */
micros_result_t show_current_color(const micros_service_args_t *args, const palette_t *palette);
/** @brief Report the selected color without rewriting the pixel. */
micros_result_t report_current_color(const micros_service_args_t *args, const palette_t *palette);
#endif
