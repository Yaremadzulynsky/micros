#ifndef MICROS_BUTTON_STATE_H
#define MICROS_BUTTON_STATE_H
#include <micros/service.h>
#include <stdbool.h>
#include "../generated/button_config.h"

#include "../generated/button_resources.h"
/* Configuration is expressed in milliseconds; runtime timers use microseconds. */
#define BUTTON_US_PER_MS UINT64_C(1000)
/* Native runtime minimum worker stack. */
#define SERVICE_STACK_BYTES 4096u

/** @brief Candidate input and last confirmed state, including startup qualification. */
typedef struct {
    uint64_t candidate_since_us;
    bool sampled;
    bool confirmed;
    bool candidate_pressed;
    bool stable_pressed;
} button_debounce_t;

/** @brief Handles, debounce history and published transition sequence for one button. */
typedef struct {
    micros_handle_t channel;
    micros_handle_t timer;
    micros_handle_t gpio;
    uint32_t sequence;
    uint64_t publisher_started_us;
    button_debounce_t debounce;
    button_config_t config;
} button_state_t;

/** @brief Return true only for the initial stable state or a confirmed state change. */
static inline bool confirm_button_state(button_debounce_t *state, bool pressed, uint64_t now_us,
                                         uint64_t debounce_us)
{
    if (!state->sampled || pressed != state->candidate_pressed) {
        state->sampled = true;
        state->candidate_pressed = pressed;
        state->candidate_since_us = now_us;
        return false;
    }
    if (now_us - state->candidate_since_us < debounce_us ||
        (state->confirmed && pressed == state->stable_pressed))
        return false;
    state->confirmed = true;
    state->stable_pressed = pressed;
    return true;
}
#endif
