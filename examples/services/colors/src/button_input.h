#ifndef MICROS_BUTTON_INPUT_H
#define MICROS_BUTTON_INPUT_H
#include <micros/service.h>
#include <stdbool.h>

/** @brief Subscription, sample ordering and stable press-edge state for one button input. */
typedef struct {
    micros_handle_t subscription;
    bool has_baseline;
    bool stable_pressed;
    uint64_t last_sample_us;
    uint64_t subscribed_us;
    uint64_t publisher_started_us;
    uint32_t last_sequence;
} button_input_t;

/** @brief Open the deployment's button channel subscription. */
micros_result_t subscribe_to_button(const micros_service_args_t *args, button_input_t *button);
/** @brief Read one sample; report a confirmed released-to-pressed edge without modifying color state.
 * Retained pre-subscription messages and changed publisher epochs establish state only.
 * Empty or lost messages report no press; invalid samples return an error. */
micros_result_t read_button_press(const micros_service_args_t *args, button_input_t *button,
                                 bool *pressed);
/** @brief Close an acquired subscription; safe after partial initialization. */
micros_result_t unsubscribe_from_button(const micros_service_args_t *args, button_input_t *button);
#endif
