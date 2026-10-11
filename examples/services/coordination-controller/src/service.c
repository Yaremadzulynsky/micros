#include "controller_ipc.h"

#define TARGET_VALUE UINT32_C(73)
#define NEC_WHITE_CODE UINT32_C(0xbb44ff00)
#define ACTION_DELAY_US UINT64_C(15000000)

typedef struct {
    micros_handle_t demo_timer;
} controller_state_t;

static void write_log(const micros_service_args_t *args, const char *text)
{
    unsigned length = 0;
    while (text[length]) {
        ++length;
    }
    args->api->debug_write(args->context, (const uint8_t *)text, length);
}

static micros_result_t request_transmission(
    const micros_service_args_t *args, micros_handle_t timer, void *user_data)
{
    (void)timer;
    (void)user_data;
    controller_operation_message_t request = {.code = NEC_WHITE_CODE};

    micros_result_t status = controller_request_operation(args, &request);
    if (!status) {
        write_log(args, "COORD CONTROLLER ACTION SUBMITTED once\n");
    }
    return status;
}

static micros_result_t start(const micros_service_args_t *args)
{
    controller_state_t *state = args->arena;
    controller_target_message_t target = {.value = TARGET_VALUE};
    micros_result_t status = controller_set_target(args, &target);
    if (status) {
        return status;
    }

    write_log(args, "COORD CONTROLLER STATE SET 73 once; runtime retains it\n");

    // One-shot application delay; delivery is handled by the runtime.
    return args->api->timer_open(args->context, ACTION_DELAY_US, 0,
                                request_transmission, NULL, &state->demo_timer);
}

static micros_result_t operation_finished(
    const micros_service_args_t *args,
    const controller_operation_result_t *outcome)
{
    const controller_operation_message_t *result = &outcome->message;
    if (outcome->status == MICROS_COORD_COMPLETED &&
        result->code == NEC_WHITE_CODE &&
        result->transmissions == 1 &&
        result->optical_matches == 1 &&
        result->applied_value == TARGET_VALUE) {
        write_log(args,
                  "COORD PROOF PASS: remote state 73, one TX, one optical RX, "
                  "action completed\n");
    } else {
        write_log(args, "COORD PROOF FAIL: inspect retained action result\n");
    }
    return MICROS_OK;
}

static micros_result_t stop(const micros_service_args_t *args)
{
    controller_state_t *state = args->arena;
    return state->demo_timer
        ? args->api->timer_close(args->context, state->demo_timer)
        : MICROS_OK;
}

static const controller_callbacks_t callbacks = {
    .on_operation_finished = operation_finished,
};

static const micros_service_hooks_t lifecycle = {
    .start = start,
    .stop = stop,
};

CONTROLLER_SERVICE(controller_state_t, 2048, lifecycle, callbacks)
