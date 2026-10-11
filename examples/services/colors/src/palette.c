#include "palette.h"
#include "../drivers/neopixel.h"

/* Six hues, dim white and off. */
#define COLOR_COUNT COLORS_INITIAL_COLOR_COUNT
/** One color choice and its diagnostic name; RGB values are converted to GRB by the driver. */
typedef struct {
    uint8_t red, green, blue;
    const char *name;
} color_t;
static const color_t colors[COLOR_COUNT] = {
    [COLORS_INITIAL_COLOR_RED] = {1, 0, 0, "red"},
    [COLORS_INITIAL_COLOR_GREEN] = {0, 1, 0, "green"},
    [COLORS_INITIAL_COLOR_BLUE] = {0, 0, 1, "blue"},
    [COLORS_INITIAL_COLOR_YELLOW] = {1, 1, 0, "yellow"},
    [COLORS_INITIAL_COLOR_CYAN] = {0, 1, 1, "cyan"},
    [COLORS_INITIAL_COLOR_MAGENTA] = {1, 0, 1, "magenta"},
    [COLORS_INITIAL_COLOR_WHITE] = {1, 1, 1, "white"},
    [COLORS_INITIAL_COLOR_OFF] = {0, 0, 0, "off"}};
micros_result_t show_current_color(const micros_service_args_t *args, const palette_t *palette)
{
    const color_t *color = &colors[palette->color_index];
    neopixel_show(color->red * palette->brightness, color->green * palette->brightness,
                  color->blue * palette->brightness);
    return report_current_color(args, palette);
}

micros_result_t report_current_color(const micros_service_args_t *args, const palette_t *palette)
{
    const color_t *color = &colors[palette->color_index];
    uint8_t message[40] = "NEOPIXEL color="; /* Prefix + longest palette name + newline. */
    uint32_t message_bytes = sizeof("NEOPIXEL color=") - 1;
    for (const char *character = color->name; *character; ++character)
        message[message_bytes++] = (uint8_t)*character;
    message[message_bytes++] = '\n';
    return args->api->debug_write(args->context, message, message_bytes);
}

void select_next_color(palette_t *palette)
{
    palette->color_index = (palette->color_index + 1) % COLOR_COUNT;
}

void configure_palette(palette_t *palette, const colors_config_t *config)
{
    palette->color_index = config->initial_color;
    palette->brightness = (uint8_t)config->brightness;
}
