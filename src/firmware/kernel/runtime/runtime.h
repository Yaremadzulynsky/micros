#ifndef MICROS_RUNTIME_H
#define MICROS_RUNTIME_H
#include <micros/service.h>
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

/* Fixed admission tables bound runtime metadata. Four service workers each
 * receive up to eight handles; a target may lower aggregate resource budgets. */
#define MICROS_RUNTIME_SERVICE_CAPACITY 4u
#define MICROS_RUNTIME_HANDLES_PER_SERVICE 8u
#ifndef MICROS_RUNTIME_HANDLE_CAPACITY
#define MICROS_RUNTIME_HANDLE_CAPACITY                                                             \
    (MICROS_RUNTIME_SERVICE_CAPACITY * MICROS_RUNTIME_HANDLES_PER_SERVICE)
#endif
#ifndef MICROS_RUNTIME_GPIO_CAPACITY
#define MICROS_RUNTIME_GPIO_CAPACITY 4u /* Host default: four exclusive simulated digital lines.   \
                                         */
#endif

/**
 * @brief Opaque manager owning service tasks, native images, and bounded resources.
 * Management calls use one controller thread; worker SDK calls are synchronized.
 * An independent supervisor detects deadlines even while the controller is idle.
 */
typedef struct micros_runtime micros_runtime_t;
/** @brief Generation-tagged service identity; zero is never a valid instance. */
typedef uint64_t micros_instance_t;

/** @brief Observable lifecycle state; terminal failures require unload before reuse. */
typedef enum {
    MICROS_STATE_UNLOADED,
    MICROS_STATE_LOADED,
    MICROS_STATE_INITIALIZING,
    MICROS_STATE_STARTING,
    MICROS_STATE_RUNNING,
    MICROS_STATE_STOPPING,
    MICROS_STATE_STOPPED,
    MICROS_STATE_FAILED
} micros_service_state_t;

/**
 * @brief Host admission ceilings and execution policy, fixed at manager creation.
 * Image bytes count serialized native payloads, not OS loader mappings. Arena and
 * requested stack bytes are service budgets; actual host stacks are separate.
 * Timeouts detect failures and do not establish real-time scheduling guarantees.
 */
typedef struct {
    size_t image_bytes;
    size_t arena_bytes;
    size_t stack_bytes;
    size_t platform_stack_bytes;
    uint32_t handle_count;
    size_t channel_bytes; /**< Aggregate admitted payload capacity, excluding fixed metadata. */
    uint64_t lifecycle_timeout_us;
    uint64_t work_timeout_us;
    uint64_t step_interval_us;
    size_t supervisor_stack_bytes; /**< Zero preserves the existing default stack budget. */
} micros_runtime_config_t;

/** @brief Resource reservations and live allocations, sampled under the manager lock. */
typedef struct {
    size_t image_bytes;
    size_t arena_bytes;
    size_t stack_bytes;
    size_t platform_stack_bytes;
    size_t arena_storage_bytes;   /**< Allocated arena bytes including alignment/minimum padding. */
    size_t kernel_metadata_bytes; /**< Fixed manager/BSP tables plus live task wrapper storage. */
    size_t supervisor_stack_bytes; /**< Host watchdog stack, separate from service stacks. */
    uint32_t reserved_handles;
    uint32_t live_handles;
    uint32_t loaded_services;
    uint32_t channels;
    size_t channel_bytes; /**< Configured payload reservations within fixed kernel storage. */
    size_t channel_storage_bytes; /**< Channel metadata plus currently allocated payload buffers. */
    size_t channel_payload_capacity; /**< Allocated payload portion of channel_storage_bytes. */
    uint32_t live_tasks;
    uint32_t active_callbacks;
    uint32_t retired_handles;  /**< Generation exhausted; slot will never be reused. */
    uint32_t retired_services; /**< Instance generation exhausted; slot is unavailable. */
    uint32_t reboot_required;  /**< Live code timed out; all reclamation is prohibited. */
} micros_runtime_usage_t;

/**
 * @brief Manifest-derived capabilities applied before a Loaded instance starts.
 * GPIO bits name lines; channel bits name configured keys 1 through 32.
 * Timer acquisitions are bounded separately from the aggregate handle quota.
 */
typedef struct {
    uint32_t timer_limit;
    uint32_t gpio_mask;
    uint32_t publish_mask;
    uint32_t subscribe_mask;
} micros_resource_policy_t;

/** @brief State, failure, and resource diagnostics for one loaded generation. */
typedef struct {
    micros_service_state_t state;
    micros_result_t result;
    uint32_t owned_handles;
    uint32_t diagnostic_writes;
    uint64_t completed_steps;
    uint64_t completed_callbacks;
    uint32_t reboot_required;
    uint32_t arena_bytes;
    uint32_t arena_alignment;
    uint32_t stack_bytes;
    size_t stack_free_bytes; /**< Measured platform watermark; host returns zero (unavailable). */
    uint32_t handle_limit, timer_limit, timers_open, gpio_granted, gpio_open;
    uint32_t publish_mask, subscribe_mask;
    uint64_t hook_max_us, callback_max_us, timer_late_max_us;
    uint32_t arena_placement;
} micros_service_status_t;

/** @brief Live channel counters under the manager lock; backlog is the slowest reader.
 * Missed counts sum messages skipped by subscribers, not merely ring overwrites. */
typedef struct {
    uint32_t key, policy, depth, payload_bytes, publishers, subscribers, backlog;
    uint64_t published, missed, age_us;
    uint32_t retained_bytes; /**< Meaningful bytes in retained messages, independent of reader backlog. */
} micros_channel_status_t;
/** Snapshot a configured channel by table slot; absent slots return an error. */
micros_result_t micros_runtime_channel_status(micros_runtime_t *runtime, uint32_t slot,
                                               micros_channel_status_t *status);

/** Return the bounded M2 host profile; callers may lower admission ceilings. */
micros_runtime_config_t micros_runtime_default_config(void);
micros_runtime_t *micros_runtime_create(const micros_runtime_config_t *config);
/** Destroy an empty, safe runtime; fails while any image is loaded or recovery is required. */
micros_result_t micros_runtime_destroy(micros_runtime_t *runtime);
/** Validate/load an independent image and reserve resources without entering service code. */
micros_result_t micros_runtime_load(micros_runtime_t *runtime, const char *image_path,
                                    uint32_t handle_quota, micros_instance_t *instance);
/** Apply admitted capabilities to an unstarted instance; fixtures may retain the default
 * unrestricted policy. */
micros_result_t micros_runtime_set_policy(micros_runtime_t *runtime, micros_instance_t instance,
                                          const micros_resource_policy_t *policy);
/* Bounded per-service configuration storage: four services cost at most 1 KiB. */
#define MICROS_CONFIG_MAX_BYTES 256u
/** Copy immutable configuration into a Loaded instance before any hook runs. */
micros_result_t micros_runtime_set_config(micros_runtime_t *runtime, micros_instance_t instance,
                                          const uint8_t *data, uint32_t bytes);
/** Launch a Loaded instance asynchronously; state changes can be polled with status. */
micros_result_t micros_runtime_start(micros_runtime_t *runtime, micros_instance_t instance);
/** Wait for startup using runtime notifications; timeout does not reclaim live code. */
micros_result_t micros_runtime_wait_running(micros_runtime_t *runtime, micros_instance_t instance,
                                             uint64_t timeout_us);
/** Request cooperative stop, wait for quiescence, join the task, and release owned handles. */
micros_result_t micros_runtime_stop(micros_runtime_t *runtime, micros_instance_t instance);
/** Park workers between native hooks/callbacks without lifecycle teardown.
 * Single controller only. While paused, do not start/stop services. Always resume
 * after a successful pause; unsafe native timeouts still require recovery. */
micros_result_t micros_runtime_pause(micros_runtime_t *runtime);
void micros_runtime_resume(micros_runtime_t *runtime);
/** Restart one admitted service using its installed image and configuration.
 * Peers and channels remain resident. Reload resets image data and the arena;
 * only the usual init/start/stop hooks run. The controller must supply the same
 * admitted launch inputs, not an unverified replacement image. Start is async.
 * A zero instance retries a failed load. After unloading, a load failure leaves
 * *instance zero; later failures leave it available for status and retry.
 * Unquiesced native code returns REBOOT_REQUIRED without reclaiming memory. */
micros_result_t micros_runtime_restart(micros_runtime_t *runtime, micros_instance_t *instance,
                                      const char *image_path, uint32_t handle_quota,
                                      const micros_resource_policy_t *policy,
                                      const uint8_t *configuration, uint32_t configuration_bytes);
/** Release a Loaded or joined terminal instance and invalidate its identity. */
micros_result_t micros_runtime_unload(micros_runtime_t *runtime, micros_instance_t instance);
/** Sample state and detect overdue hooks. A timeout retains all owned memory until process exit. */
micros_result_t micros_runtime_status(micros_runtime_t *runtime, micros_instance_t instance,
                                      micros_service_status_t *status);
/** Configure a stream/latest channel without package metadata; key must be nonzero.
 * New subscribers begin at the oldest retained stream message, or newest latest value. */
micros_result_t micros_runtime_channel_create(micros_runtime_t *runtime, uint32_t key,
                                              uint32_t policy, uint32_t depth,
                                              uint32_t payload_bytes);
/** Discard a channel and invalidate its publisher/subscriber handles by generation. */
micros_result_t micros_runtime_channel_destroy(micros_runtime_t *runtime, uint32_t key);
micros_runtime_usage_t micros_runtime_usage(micros_runtime_t *runtime);
const char *micros_runtime_state_name(micros_service_state_t state);
/** Privileged physical-console bridge: use an existing running service's open
 * port and cursor. No new resource rights are granted. Not a service ABI. */
micros_result_t micros_runtime_console_write(micros_runtime_t *, micros_instance_t,
    uint32_t key, const uint8_t *, uint32_t bytes);
micros_result_t micros_runtime_console_read(micros_runtime_t *, micros_instance_t,
    uint32_t key, uint8_t *, uint32_t capacity, uint32_t *bytes, micros_message_info_t *);
micros_result_t micros_runtime_coord_bind(micros_runtime_t *, uint32_t, uint32_t, uint32_t, uint64_t);
micros_result_t micros_runtime_coord_exchange(micros_runtime_t *, uint32_t,
    const uint8_t *, uint32_t, uint8_t *, uint32_t *);
uint64_t micros_runtime_coord_identity(micros_runtime_t *, uint32_t);
#ifdef __cplusplus
}
#endif
#endif
