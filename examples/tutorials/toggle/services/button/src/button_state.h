#ifndef BUTTON_STATE_H
#define BUTTON_STATE_H
#include <stdbool.h>
#include <stdint.h>

typedef struct {
    bool initialized, valid;
    bool candidate, pressed;
    uint64_t changed_us;
} button_state_t;

/* True only when the first stable state or a change is confirmed. */
static inline bool button_confirm(button_state_t *s, bool raw_pressed,
                                  uint64_t now_us, uint64_t debounce_us)
{
    if (!s->initialized || raw_pressed != s->candidate) {
        s->initialized = true;
        s->candidate = raw_pressed;
        s->changed_us = now_us;
    }
    if (now_us - s->changed_us < debounce_us) return false;
    if (s->valid && s->pressed == s->candidate) return false;
    s->pressed = s->candidate;
    s->valid = true;
    return true;
}
#endif
