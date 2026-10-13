#include "../../src/sdk/abi/internal/micros/ipc.h"
#include "button_input.h"
#include "button_state.h"
#include "palette.h"
#include "button_state.codec.h"
#include <assert.h>
#include <stdio.h>
/* Feed encoded messages through the public input API, without pixel hardware. */
static micros_button_v1_ButtonState pending_sample;
static micros_result_t next_read_result;
static uint32_t sequence_increment = 1;
static uint64_t publisher_started_us = 1;
static uint32_t explicit_sequence;
static micros_result_t read_sample(micros_context_t *context, micros_handle_t channel,
                                   uint8_t *bytes, uint32_t capacity, uint32_t *byte_count,
                                   micros_message_info_t *info)
{
    (void)context;
    (void)channel;
    (void)info;
    if (next_read_result)
        return next_read_result;
    return micros_button_v1_ButtonState_encode(&pending_sample, bytes, capacity, byte_count);
}
static uint8_t displayed_red, displayed_green, displayed_blue;
void neopixel_show(uint8_t red, uint8_t green, uint8_t blue)
{
    displayed_red = red;
    displayed_green = green;
    displayed_blue = blue;
}
static micros_result_t accept_diagnostic(micros_context_t *context, const uint8_t *message,
                                         uint32_t bytes)
{
    (void)context;
    (void)message;
    (void)bytes;
    return MICROS_OK;
}
static bool sample_press(button_input_t *button, bool pressed, uint64_t timestamp)
{
    static const struct micros_ipc_api ipc = {.ipc_read = read_sample};
    static const micros_api_t api = {._ipc = &ipc};
    const micros_service_args_t args = {.api = &api};
    pending_sample = (micros_button_v1_ButtonState){explicit_sequence ? explicit_sequence : button->last_sequence + sequence_increment, timestamp, pressed, publisher_started_us};
    bool detected;
    assert(read_button_press(&args, button, &detected) == MICROS_OK);
    return detected;
}
int main(void)
{
    button_debounce_t debounce = {0};
    assert(!confirm_button_state(&debounce, false, 1, 40000));
    assert(!confirm_button_state(&debounce, false, 20001, 40000));
    assert(confirm_button_state(&debounce, false, 40001, 40000)); /* Initial stable baseline. */
    assert(!confirm_button_state(&debounce, false, 60001, 40000));
    assert(!confirm_button_state(&debounce, true, 80001, 40000));
    assert(!confirm_button_state(&debounce, false, 100001, 40000)); /* Bounce cancels press. */
    assert(!confirm_button_state(&debounce, true, 120001, 40000));
    assert(!confirm_button_state(&debounce, true, 140001, 40000));
    assert(confirm_button_state(&debounce, true, 160001, 40000));
    assert(!confirm_button_state(&debounce, true, 500001, 40000)); /* No repeat while held. */
    assert(!confirm_button_state(&debounce, false, 520001, 40000));
    assert(confirm_button_state(&debounce, false, 560001, 40000));
    button_debounce_t boot_held = {0};
    assert(!confirm_button_state(&boot_held, true, 1, 40000));
    assert(confirm_button_state(&boot_held, true, 40001, 40000));
    assert(!confirm_button_state(&boot_held, true, 80001, 40000));

    button_input_t button = {0};
    palette_t palette = {0};
    assert(!sample_press(&button, true, 40001)); /* Boot-held baseline is not a press. */
    assert(!sample_press(&button, false, 560001));
    assert(sample_press(&button, true, 660001));
    assert(palette.color_index == 0); /* Input never changes the palette. */
    select_next_color(&palette);
    assert(palette.color_index == 1);
    assert(!sample_press(&button, true, 760001)); /* Duplicate state is not another press. */
    for (unsigned press = 1; press < 8; ++press) { /* Six hues, white and off. */
        assert(!sample_press(&button, false, 760001 + press * 200000));
        assert(sample_press(&button, true, 860001 + press * 200000));
        select_next_color(&palette);
    }
    assert(palette.color_index == 0);
    assert(!sample_press(&button, false, 2500001));
    sequence_increment = 2; /* Even without a queue-loss reply, a gap resets the baseline. */
    assert(!sample_press(&button, true, 2600001));
    sequence_increment = 1;
    assert(!sample_press(&button, false, 2700001));
    next_read_result = MICROS_ERROR_MESSAGES_MISSED;
    assert(!sample_press(&button, true, 2800001));
    next_read_result = MICROS_OK;
    assert(!sample_press(&button, true, 2900001));
    assert(!sample_press(&button, false, 3000001));
    assert(sample_press(&button, true, 3100001));
    /* Subscriber restart: retained release/press pairs update state, not color. */
    button = (button_input_t){.subscribed_us = 4000000};
    assert(!sample_press(&button, false, 3200001));
    assert(!sample_press(&button, true, 3300001));
    assert(!sample_press(&button, false, 3400001));
    assert(sample_press(&button, true, 4100001));
    /* Publisher restart: sequence reset and held button establish a new baseline. */
    publisher_started_us = 4200000;
    explicit_sequence = 1;
    assert(!sample_press(&button, true, 4300001));
    explicit_sequence = 0;
    assert(!sample_press(&button, false, 4400001));
    assert(sample_press(&button, true, 4500001));
    button_debounce_t shorter_debounce = {0};
    assert(!confirm_button_state(&shorter_debounce, true, 1, 10000));
    assert(confirm_button_state(&shorter_debounce, true, 10001, 10000));
    colors_config_t configuration = {.brightness = 7, .initial_color = COLORS_INITIAL_COLOR_BLUE};
    configure_palette(&palette, &configuration);
    const micros_api_t api = {.debug_write = accept_diagnostic};
    const micros_service_args_t args = {.api = &api};
    assert(show_current_color(&args, &palette) == MICROS_OK);
    assert(displayed_red == 0 && displayed_green == 0 && displayed_blue == 7);
    select_next_color(&palette);
    assert(show_current_color(&args, &palette) == MICROS_OK);
    assert(displayed_red == 7 && displayed_green == 7 && displayed_blue == 0);
    puts("PASS publisher debounce, initial baseline, press edges, holding and palette wrap");
}
