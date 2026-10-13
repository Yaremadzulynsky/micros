#include <micros/service.h>

#ifndef MICROS_SERVICE_TARGET
#error MICROS_SERVICE_TARGET must be set by the target build
#endif

#ifndef MICROS_SERVICE_VARIANT
#define MICROS_SERVICE_VARIANT "v1"
#endif

/*
 * These markers exercise two different parts of the native image: initialized
 * data and zero-initialized storage (BSS). Volatile keeps their reads and writes
 * observable so the example checks the loader's work on every fresh load.
 */
/* 7 is an arbitrary nonzero sentinel; 9 and 11 below deliberately differ so
 * failed reset/retention checks cannot pass by seeing the same marker twice. */
static volatile uint32_t initialized_data_marker = 7;
static volatile uint32_t bss_marker;

/**
 * @brief Hello-service state stored in the loader-provided, initially zeroed arena.
 *
 * Tracks lifecycle progress and a monotonic timestamp across hooks. The example
 * checks this state to verify initialization, retention, and reset on reload.
 */
typedef struct {
    /** Number of successfully completed step hooks in this load cycle. */
    uint32_t completed_step_count;
    /** Nonzero after start has run; checked before each step. */
    uint32_t has_started;
    /** Monotonic time captured during init, in microseconds. */
    uint64_t initialization_time_us;
} hello_service_state_t;

/* Accept string literals only; omit the terminating NUL from the diagnostic. */
#define WRITE_DIAGNOSTIC_LITERAL(service_args, message_literal) \
    ((service_args)->api->debug_write( \
        (service_args)->context, \
        (const uint8_t *)(message_literal), \
        (uint32_t)(sizeof(message_literal) - 1)))

static micros_result_t service_initialize(const micros_service_args_t *service_args)
{
    hello_service_state_t *service_state = service_args->arena;

    /* Reloading must restore both image storage and the service-owned arena. */
    if (initialized_data_marker != 7 || bss_marker != 0 ||
        service_state->completed_step_count != 0 ||
        service_state->has_started != 0 ||
        service_state->initialization_time_us != 0) {
        return MICROS_ERROR_SERVICE;
    }

    /* Later hooks must see these changes; the next load must discard them. */
    initialized_data_marker = 9;
    bss_marker = 11;
    service_state->initialization_time_us =
        service_args->api->monotonic_us(service_args->context);

    return WRITE_DIAGNOSTIC_LITERAL(
        service_args, "hello " MICROS_SERVICE_VARIANT " init globals=7 bss=0 arena=0\n");
}

static micros_result_t service_start(const micros_service_args_t *service_args)
{
    hello_service_state_t *service_state = service_args->arena;

    service_state->has_started = 1;
    return WRITE_DIAGNOSTIC_LITERAL(
        service_args, "hello " MICROS_SERVICE_VARIANT " start\n");
}

static micros_result_t service_step(const micros_service_args_t *service_args)
{
    hello_service_state_t *service_state = service_args->arena;

    /* Check lifecycle order, retained state, and the SDK's monotonic clock. */
    if (service_state->has_started == 0 ||
        initialized_data_marker != 9 || bss_marker != 11 ||
        service_args->api->monotonic_us(service_args->context) <
            service_state->initialization_time_us) {
        return MICROS_ERROR_SERVICE;
    }

    ++service_state->completed_step_count;
    return WRITE_DIAGNOSTIC_LITERAL(
        service_args, "hello " MICROS_SERVICE_VARIANT " step\n");
}

static micros_result_t service_stop(const micros_service_args_t *service_args)
{
    hello_service_state_t *service_state = service_args->arena;

    /*
     * The M1 harness runs exactly three steps. This is a demo assertion;
     * a general service must also support cleanup after partial initialization.
     * This example acquires no external resources that need releasing.
     */
    if (service_state->completed_step_count != 3) {
        return MICROS_ERROR_SERVICE;
    }

    return WRITE_DIAGNOSTIC_LITERAL(
        service_args, "hello " MICROS_SERVICE_VARIANT " stop steps=3\n");
}

/* Describe the ABI, memory budget, and hooks without exposing kernel internals. */
const micros_service_descriptor_t micros_descriptor = {
    .struct_bytes = sizeof(micros_service_descriptor_t),
    .abi_major = MICROS_ABI_MAJOR,
    .abi_revision = MICROS_ABI_REVISION,
    .target = MICROS_SERVICE_TARGET,
    .arena_bytes = sizeof(hello_service_state_t),
    .arena_alignment = 8, /* Preserve 8-byte alignment for the uint64 timestamp. */
    .stack_bytes = 4096, /* M1's measured 4 KiB demo stack, not a general minimum. */
    .reserved = 0,
    .init = service_initialize,
    .start = service_start,
    .step = service_step,
    .stop = service_stop,
};

/* Host loaders discover this entry point; the MCU reads the descriptor directly. */
const micros_service_descriptor_t *micros_service_query(void)
{
    return &micros_descriptor;
}
