#include <micros/service.h>
/* Compile one independently loaded image per named fault scenario. */
#ifndef FIXTURE_MODE
#define FIXTURE_MODE NORMAL
#endif
#define NORMAL 0
#define FAIL_INIT 1
#define FAIL_START 2
#define FAIL_STOP 3
#define HANG_INIT 4
#define HANG_START 5
#define HANG_STEP 6
#define HANG_STOP 7
#define HANG_CALLBACK 8
#define SLOW_INIT 9
#define SLOW_CALLBACK 10
#define HANDLE_CHECKS 11
#define CALLBACK_ERROR 12
#define FAIL_STEP 13
#define SLOW_START 14
#define SLOW_BOTH 15

/* Timing fixtures hold a hook for 50 ms, within the test's 500 ms budget, so
 * the controller can request stop while native code is demonstrably active. */
#if FIXTURE_MODE == SLOW_BOTH
#define HOLD_US UINT64_C(200000)
#else
#define HOLD_US UINT64_C(50000)
#endif
#define TIMER_US UINT64_C(1000) /* Short period makes callback tests finish promptly. */
#ifndef FIXTURE_LINE
#define FIXTURE_LINE 0u /* Default exclusive line; peer fixture uses the next line. */
#endif
#define FIXTURE_STACK_BYTES 4096u /* Match the admitted M1 minimum. */
#define TEST_HANDLE_CAPACITY 8u   /* Runtime's per-service ceiling, exercised exactly. */
#define DIAGNOSTIC(args, literal)                                                                  \
    ((args)->api->debug_write((args)->context, (const uint8_t *)(literal), sizeof(literal) - 1))

/** @brief Fixture state used to prove arena zeroing and serialized callback ownership. */
typedef struct {
    micros_handle_t gpio;
    micros_handle_t timer;
    uint32_t callbacks;
    uint32_t started;
} fixture_state_t;
/* Distinct nonzero sentinels test restored initialized data and BSS on reload. */
static volatile unsigned initialized_marker = 17;
static volatile unsigned bss_marker;
static void hang(void)
{
    for (;;) {
    }
}
static void hold(const micros_service_args_t *args)
{
    uint64_t deadline = args->api->monotonic_us(args->context) + HOLD_US;
    while (args->api->monotonic_us(args->context) < deadline) {
    }
}
static micros_result_t callback(const micros_service_args_t *args, micros_handle_t timer,
                                void *user_data)
{
    (void)timer;
    fixture_state_t *state = user_data;
    DIAGNOSTIC(args, "callback entered\n");
    if (FIXTURE_MODE == HANG_CALLBACK)
        hang();
    if (FIXTURE_MODE == SLOW_CALLBACK)
        hold(args);
    if (FIXTURE_MODE == CALLBACK_ERROR)
        return MICROS_ERROR_SERVICE;
    uint32_t level;
    if (args->api->gpio_read(args->context, state->gpio, &level))
        return MICROS_ERROR_SERVICE;
    if (args->api->gpio_write(args->context, state->gpio, !level))
        return MICROS_ERROR_SERVICE;
    ++state->callbacks;
    return MICROS_OK;
}
static micros_result_t initialize(const micros_service_args_t *args)
{
    fixture_state_t *state = args->arena;
    if (initialized_marker != 17 || bss_marker || state->gpio || state->timer || state->callbacks ||
        state->started)
        return MICROS_ERROR_SERVICE;
    initialized_marker = 18;
    bss_marker = 19;
    if (args->api->gpio_open(args->context, FIXTURE_LINE, &state->gpio))
        return MICROS_ERROR_SERVICE;
    DIAGNOSTIC(args, "init entered\n");
    if (FIXTURE_MODE == HANG_INIT)
        hang();
    if (FIXTURE_MODE == SLOW_INIT || FIXTURE_MODE == SLOW_BOTH)
        hold(args);
    if (FIXTURE_MODE == FAIL_INIT)
        return MICROS_ERROR_SERVICE;
    if (FIXTURE_MODE == HANDLE_CHECKS) {
        micros_handle_t old_gpio = state->gpio;
        if (args->api->gpio_close(args->context, old_gpio))
            return MICROS_ERROR_SERVICE;
        if (args->api->gpio_open(args->context, FIXTURE_LINE, &state->gpio))
            return MICROS_ERROR_SERVICE;
        uint32_t level;
        if (state->gpio == old_gpio ||
            args->api->gpio_read(args->context, old_gpio, &level) != MICROS_ERROR_STALE_HANDLE)
            return MICROS_ERROR_SERVICE;
        if (args->api->timer_close(args->context, state->gpio) != MICROS_ERROR_STALE_HANDLE)
            return MICROS_ERROR_SERVICE;
        micros_handle_t timers[TEST_HANDLE_CAPACITY];
        /* One GPIO occupies the first handle; fill the remaining seven. */
        for (unsigned slot = 0; slot < TEST_HANDLE_CAPACITY - 1; ++slot)
            if (args->api->timer_open(args->context, HOLD_US, 0, callback, state, &timers[slot]))
                return MICROS_ERROR_SERVICE;
        if (args->api->timer_open(args->context, HOLD_US, 0, callback, state,
                                  &timers[TEST_HANDLE_CAPACITY - 1]) != MICROS_ERROR_CAPACITY)
            return MICROS_ERROR_SERVICE;
        for (unsigned slot = 0; slot < TEST_HANDLE_CAPACITY - 1; ++slot) {
            if (args->api->timer_close(args->context, timers[slot]))
                return MICROS_ERROR_SERVICE;
            if (args->api->timer_close(args->context, timers[slot]) != MICROS_ERROR_STALE_HANDLE)
                return MICROS_ERROR_SERVICE;
        }
        /* Invalid and overflowing timer requests must not consume a slot. */
        if (args->api->timer_open(args->context, UINT64_MAX, 0, callback, state, &timers[0]) !=
            MICROS_ERROR_INVALID_ARGUMENT)
            return MICROS_ERROR_SERVICE;
    }
    return MICROS_OK;
}
static micros_result_t start(const micros_service_args_t *args)
{
    fixture_state_t *state = args->arena;
    state->started = 1;
    DIAGNOSTIC(args, "start entered\n");
    if (FIXTURE_MODE == HANG_START)
        hang();
    if (FIXTURE_MODE == SLOW_START || FIXTURE_MODE == SLOW_BOTH) {
        hold(args);
        return MICROS_OK;
    }
    if (FIXTURE_MODE == FAIL_START)
        return MICROS_ERROR_SERVICE;
    return args->api->timer_open(args->context, TIMER_US, TIMER_US, callback, state, &state->timer);
}
static micros_result_t step(const micros_service_args_t *args)
{
    (void)args;
    if (FIXTURE_MODE == HANG_STEP)
        hang();
    return FIXTURE_MODE == FAIL_STEP ? MICROS_ERROR_SERVICE : MICROS_OK;
}
static micros_result_t stop(const micros_service_args_t *args)
{
    fixture_state_t *state = args->arena;
    DIAGNOSTIC(args, "stop entered\n");
    if (FIXTURE_MODE == HANG_STOP)
        hang();
    /* New registrations must be blocked while cleanup still permits release. */
    micros_handle_t unexpected;
    if (args->api->timer_open(args->context, TIMER_US, 0, callback, state, &unexpected) !=
        MICROS_ERROR_STATE)
        return MICROS_ERROR_SERVICE;
    if (FIXTURE_MODE == FAIL_INIT || FIXTURE_MODE == FAIL_STOP)
        return MICROS_ERROR_SERVICE;
    if (state->timer && args->api->timer_close(args->context, state->timer))
        return MICROS_ERROR_SERVICE;
    if (state->gpio && args->api->gpio_close(args->context, state->gpio))
        return MICROS_ERROR_SERVICE;
    return MICROS_OK;
}
/** @brief Independently linked fault fixture using only the public service ABI. */
static const micros_service_descriptor_t descriptor = {.struct_bytes =
                                                           sizeof(micros_service_descriptor_t),
                                                       .abi_major = MICROS_ABI_MAJOR,
                                                       .abi_revision = MICROS_ABI_REVISION,
                                                       .target = MICROS_BUILD_TARGET,
                                                       .arena_bytes = sizeof(fixture_state_t),
                                                       .arena_alignment = _Alignof(fixture_state_t),
                                                       .stack_bytes = FIXTURE_STACK_BYTES,
                                                       .init = initialize,
                                                       .start = start,
                                                       .step = step,
                                                       .stop = stop};
const micros_service_descriptor_t *micros_service_query(void)
{
    return &descriptor;
}
