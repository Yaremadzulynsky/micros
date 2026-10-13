#ifndef MICROS_SERVICE_H
#define MICROS_SERVICE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Experimental native interface, not an on-disk image header. */
/* ABI 0 is experimental; revision 7 adds runtime-owned coordination dispatch. */
#define MICROS_ABI_MAJOR UINT32_C(0)
#define MICROS_ABI_REVISION UINT32_C(7)
/* Project-assigned profile IDs distinguish incompatible native calling conventions. */
#define MICROS_TARGET_MACOS_ARM64 UINT32_C(1)
#define MICROS_TARGET_ESP32_XTENSA UINT32_C(2)
#define MICROS_TARGET_LINUX_ARM64 UINT32_C(3)
#define MICROS_TARGET_LINUX_X86_64 UINT32_C(4)
#define MICROS_TARGET_ARMV6M UINT32_C(5)
#define MICROS_TARGET_ESP8266_XTENSA UINT32_C(6)
#if defined(__linux__) && defined(__aarch64__)
#define MICROS_BUILD_TARGET MICROS_TARGET_LINUX_ARM64
#elif defined(__linux__) && defined(__x86_64__)
#define MICROS_BUILD_TARGET MICROS_TARGET_LINUX_X86_64
#elif defined(__XTENSA__) && defined(__XTENSA_CALL0_ABI__) && defined(__XTENSA_EL__)
#define MICROS_BUILD_TARGET MICROS_TARGET_ESP8266_XTENSA
#elif defined(__XTENSA__)
#define MICROS_BUILD_TARGET MICROS_TARGET_ESP32_XTENSA
#elif defined(__ARM_ARCH_6M__) && defined(__thumb__) && defined(__ARM_EABI__) && \
      !defined(__ARMEB__) && !defined(__linux__)
#define MICROS_BUILD_TARGET MICROS_TARGET_ARMV6M
#elif defined(__APPLE__) && defined(__aarch64__)
#define MICROS_BUILD_TARGET MICROS_TARGET_MACOS_ARM64
#else
#error "Unsupported micros native target"
#endif
/* M1 caps each synchronous diagnostic copy at 256 bytes to bound work/storage;
 * this is prototype policy, not a UART or protobuf payload limit. */
#define MICROS_DEBUG_MAX_BYTES UINT32_C(256)

typedef int32_t micros_result_t;
/* Zero is success; distinct negative ABI codes identify the failure category. */
#define MICROS_OK INT32_C(0)
#define MICROS_ERROR_INVALID_ARGUMENT (-INT32_C(1))
#define MICROS_ERROR_CAPACITY (-INT32_C(2))
#define MICROS_ERROR_STATE (-INT32_C(3))
#define MICROS_ERROR_UNSUPPORTED (-INT32_C(4))
#define MICROS_ERROR_SERVICE (-INT32_C(5))
#define MICROS_ERROR_STALE_HANDLE (-INT32_C(6))
#define MICROS_ERROR_BUSY (-INT32_C(7))
#define MICROS_ERROR_REBOOT_REQUIRED (-INT32_C(8))
#define MICROS_ERROR_EMPTY (-INT32_C(9))
#define MICROS_ERROR_MESSAGES_MISSED (-INT32_C(10))
/* ABI constants, rather than C enums, keep the public representation explicit. */
#define MICROS_CHANNEL_STREAM UINT32_C(1)
#define MICROS_CHANNEL_LATEST UINT32_C(2)
#define MICROS_IPC_PUBLISH UINT32_C(1)
#define MICROS_IPC_SUBSCRIBE UINT32_C(2)

/**
 * @brief Opaque kernel-owned state identifying one loaded service instance.
 *
 * Pass this pointer back to API callbacks unchanged. Services must not inspect,
 * allocate, or free it; the loader keeps it valid through completion of stop.
 */
typedef struct micros_context micros_context_t;

typedef struct micros_service_args micros_service_args_t;

/** @brief Opaque owner-checked, generation-tagged resource identity; zero is invalid. */
typedef uint64_t micros_handle_t;

/**
 * @brief Timer work serialized with lifecycle hooks on the service's managed task.
 * user_data must remain valid until the timer is closed or stop completes.
 * A nonzero result fails the service and enters cooperative cleanup.
 */
typedef micros_result_t (*micros_timer_callback_t)(const micros_service_args_t *args,
                                                 micros_handle_t timer, void *user_data);

/**
 * @brief Result metadata for one synchronous channel read.
 * Stream loss reports the oldest retained sequence and how many were overwritten,
 * without returning a message. Latest reads report intentionally skipped samples.
 */
typedef struct micros_message_info {
    uint64_t sequence;
    uint64_t messages_missed;
} micros_message_info_t;

/**
 * @brief Kernel callbacks available to a service through the native ABI.
 *
 * The loader supplies this read-only table with matching ABI identifiers and
 * keeps it valid through stop. Callbacks use the instance's micros_context_t.
 */
typedef struct micros_api {
    /** Size of this native table in bytes; initialize with sizeof(micros_api_t). */
    uint32_t struct_bytes;
    /** ABI major version; must match MICROS_ABI_MAJOR. */
    uint32_t abi_major;
    /** Exact layout revision; must match MICROS_ABI_REVISION. */
    uint32_t abi_revision;
    /** Reserved for future ABI fields; must be zero. */
    uint32_t reserved;
    /**
     * Write up to MICROS_DEBUG_MAX_BYTES of diagnostics synchronously.
     * Arguments are instance context, message buffer, and byte count. The
     * buffer is not retained. Returns MICROS_OK or a negative error code.
     */
    micros_result_t (*debug_write)(micros_context_t *, const uint8_t *, uint32_t);
    /** Read monotonic time in microseconds; the origin is platform-specific. */
    uint64_t (*monotonic_us)(micros_context_t *);
    /**
     * Reserve a timer due after delay_us; period_us zero selects one-shot delivery.
     * Late periodic delivery is coalesced, never replayed in an unbounded burst.
     * Timers consume one handle until closed, including expired one-shot timers.
     * New resources are rejected during stop. Unsupported BSPs return UNSUPPORTED.
     */
    micros_result_t (*timer_open)(micros_context_t *, uint64_t delay_us, uint64_t period_us,
                                 micros_timer_callback_t, void *user_data, micros_handle_t *);
    /** Close an owned timer; no later callback will be dispatched for this handle. */
    micros_result_t (*timer_close)(micros_context_t *, micros_handle_t);
    /** Reserve an exclusive simulated digital line; M2 host provides lines 0 through 3. */
    micros_result_t (*gpio_open)(micros_context_t *, uint32_t line, micros_handle_t *);
    /** Read a reserved line's simulated level (zero or one). */
    micros_result_t (*gpio_read)(micros_context_t *, micros_handle_t, uint32_t *level);
    /** Set a reserved line's simulated level to zero or one. */
    micros_result_t (*gpio_write)(micros_context_t *, micros_handle_t, uint32_t level);
    /** Release a reserved line; stale or foreign handles are rejected. */
    micros_result_t (*gpio_close)(micros_context_t *, micros_handle_t);
    /** Opaque SDK dispatch. IPC operations are exposed only by generated service bindings. */
    const struct micros_ipc_api *_ipc;

    /** Read an owned analog-capable input as a raw 12-bit count (0..4095).
     * ESP32 supports ADC1 inputs only, with 12 dB attenuation. No calibration
     * or voltage conversion is implied. Unsupported platforms return UNSUPPORTED.
     * The pin remains exclusively owned until gpio_close; output is unchanged on error.
     */
    micros_result_t (*gpio_read_analog)(micros_context_t *, micros_handle_t, uint32_t *raw);

} micros_api_t;

/**
 * @brief Loader-provided resources passed to every service lifecycle hook.
 *
 * The arguments and referenced objects remain valid through stop completion.
 * The service may retain them within its own state, but must not free them or
 * share them with another service. Only the arena is service-writable storage.
 */
struct micros_service_args {
    /** Size of this argument block in bytes: sizeof(micros_service_args_t). */
    uint32_t struct_bytes;
    /** Number of writable bytes available at arena. */
    uint32_t arena_bytes;
    /** Opaque instance identity to pass to API callbacks. */
    micros_context_t *context;
    /** Kernel callback table for this instance. */
    const micros_api_t *api;
    /** Service state storage, zeroed before init and aligned as requested. */
    void *arena;
    /** Immutable encoded configuration, valid through stop; NULL when no payload is supplied. */
    const uint8_t *config_data;
    /** Encoded payload length; decode and validate before using configuration. */
    uint32_t config_bytes;
};

/**
 * @brief Bounded lifecycle operation executed on the service's managed task.
 *
 * Hooks run serially; args and its referenced objects live through stop.
 * Return MICROS_OK on success or a negative MICROS_ERROR_* code on failure.
 */
typedef micros_result_t (*micros_service_hook_t)(const micros_service_args_t *args);

/**
 * @brief Service-published ABI identity, memory requirements, and lifecycle hooks.
 *
 * The loader validates this descriptor before running the service, provisions
 * its arena and stack, and dispatches init, start, step, and stop on one managed
 * task. All four hooks are required. The descriptor belongs to the loaded image
 * and must remain valid until unload. This is a native, pointer-bearing ABI
 * structure, not the serialized .mimg header.
 */
typedef struct micros_service_descriptor {
    /** Exact native layout size: sizeof(micros_service_descriptor_t). */
    uint32_t struct_bytes;
    /** Required ABI major version; use MICROS_ABI_MAJOR. */
    uint32_t abi_major;
    /** Required exact ABI revision; use MICROS_ABI_REVISION. */
    uint32_t abi_revision;
    /** Native calling-convention profile, identified by MICROS_TARGET_* values. */
    uint32_t target;
    /** Requested zero-initialized service state storage, in bytes. */
    uint32_t arena_bytes;
    /** Required arena alignment in bytes; a nonzero power of two. */
    uint32_t arena_alignment;
    /** Requested managed-task stack size in bytes, subject to platform limits. */
    uint32_t stack_bytes;
    /** Arena placement: 0 = internal RAM, 1 = PSRAM. Set by package builder. */
    uint32_t reserved;
    /** Initialize service state using the loader-provided resources. */
    micros_service_hook_t init;
    /** Begin service operation after init succeeds. */
    micros_service_hook_t start;
    /** Perform one bounded unit of work after start succeeds. */
    micros_service_hook_t step;
    /** Release service resources; must also handle partial initialization. */
    micros_service_hook_t stop;
} micros_service_descriptor_t;

/**
 * @brief Return the loaded service's descriptor for host-side discovery.
 *
 * The returned pointer belongs to the service image and is valid until unload.
 * The M1 ESP32 loader instead finds the descriptor directly in image data.
 */
const micros_service_descriptor_t *micros_service_query(void);

#ifdef __cplusplus
}
#endif

#endif
