#include "runtime.h"
#include "../../../sdk/abi/internal/micros/ipc.h"
#include "channel.h"
#include "image.h"
#include "m1_limits.h"
#include <micros/platform.h>
#include <micros/memory.h>
#include <stdlib.h>
#include <string.h>

/* Identities pack a nonzero 32-bit generation above a one-based 32-bit slot.
 * Exhaustion retires a slot instead of wrapping and accepting a stale identity. */
#define ID_SLOT_BITS 32u
#define ID_SLOT_MASK UINT64_C(0xffffffff)
#define US_PER_MS UINT64_C(1000)
/* The multi-service M3 demo exposed >10 ms desktop descheduling during console
 * output. The default 100 ms work threshold detects hangs; it is a watchdog policy,
 * not a scheduling-latency guarantee. BSP controllers may select a tighter budget. */
#define DEFAULT_WORK_TIMEOUT_US UINT64_C(100000)

typedef struct service_slot service_slot_t;
/** @brief Resource payload discriminator; internal values never cross the ABI. */
typedef enum {
    RESOURCE_FREE,
    RESOURCE_TIMER,
    RESOURCE_GPIO,
    RESOURCE_PUBLISHER,
    RESOURCE_SUBSCRIBER
} resource_kind_t;
/** @brief Private API context binding callbacks to one manager-owned service slot. */
struct micros_context {
    struct micros_runtime *runtime;
    service_slot_t *service;
};
/** @brief Fixed resource slot; payload is meaningful only while owned by a service. */
typedef struct {
    micros_instance_t owner;
    uint32_t generation;
    resource_kind_t kind;
    /* A handle has exactly one kind. Channel/GPIO state never coexists with
     * a timer's callback and deadline; share their bounded storage. */
    union {
        struct { uint32_t line, channel_slot, channel_generation; uint64_t next_sequence; };
        struct { uint64_t due_us, period_us; micros_timer_callback_t callback; void *user_data; int armed; };
    };
} resource_slot_t;
/**
 * @brief One admitted image and its serialized worker lifecycle.
 * All mutable coordination fields are protected by the manager lock; service
 * code only accesses its own arena and calls back through its opaque context.
 */
struct service_slot {
    uint32_t generation;
    micros_instance_t identity;
    micros_service_state_t state;
    micros_result_t result;
    micros_platform_image_t *image;
    const micros_service_descriptor_t *descriptor;
    micros_service_args_t args;
    uint8_t *config_data;
    micros_context_t context;
    micros_platform_task_t *task;
    size_t image_bytes;
    size_t arena_storage_bytes;
    size_t platform_stack_bytes;
#ifdef MICROS_STATIC_MEMORY
    void *stack_storage;
#endif
    uint32_t handle_quota;
    micros_resource_policy_t policy;
    int policy_enabled;
    uint32_t owned_handles;
    uint32_t diagnostic_writes;
    uint64_t completed_steps;
    uint64_t completed_callbacks;
    uint64_t hook_max_us, callback_max_us, timer_late_max_us;
    uint64_t deadline_us;
    int phase_active;
    int stop_requested;
    int finished;
};
/** @brief Fixed admission tables and coordination shared by every platform. */
#include "../coordination/engine.h"
#ifdef MICROS_STATIC_MEMORY
_Static_assert(sizeof(micros_coord_channel_t) == 224, "Update the host static-memory admission cost");
#endif
struct micros_runtime {
    micros_runtime_config_t config;
    micros_runtime_usage_t usage;
    micros_platform_sync_t *sync;
    service_slot_t services[MICROS_RUNTIME_SERVICE_CAPACITY];
    resource_slot_t resources[MICROS_RUNTIME_HANDLE_CAPACITY];
    micros_channel_t channels[MICROS_CHANNEL_CAPACITY];
    micros_coord_channel_t *coordination[MICROS_CHANNEL_CAPACITY];
    uint64_t channel_missed[MICROS_CHANNEL_CAPACITY];
    uint64_t channel_last_us[MICROS_CHANNEL_CAPACITY];
    micros_platform_gpio_t *gpio;
    micros_platform_task_t *supervisor;
    int shutdown;
    int paused;
};

#ifdef MICROS_STATIC_MEMORY
/* One controller owns one runtime on these targets. A poisoned runtime is never
 * reclaimed, so a stalled service cannot write into a replacement instance. */
static micros_runtime_t static_runtime;
static int static_runtime_owned;
static micros_runtime_t *runtime_allocate(void) {
    if (static_runtime_owned) return NULL;
    static_runtime_owned = 1;
    memset(&static_runtime, 0, sizeof(static_runtime));
    return &static_runtime;
}
static void runtime_release(micros_runtime_t *runtime) {
    (void)runtime;
    static_runtime_owned = 0;
}
#else
static micros_runtime_t *runtime_allocate(void) { return calloc(1, sizeof(micros_runtime_t)); }
static void runtime_release(micros_runtime_t *runtime) { free(runtime); }
#endif

static uint64_t identity(uint32_t generation, size_t slot)
{
    return (uint64_t)generation << ID_SLOT_BITS | (slot + 1);
}
static service_slot_t *find_service(micros_runtime_t *runtime, micros_instance_t instance)
{
    uint64_t slot = instance & ID_SLOT_MASK;
    if (!slot || slot > MICROS_RUNTIME_SERVICE_CAPACITY)
        return NULL;
    service_slot_t *service = &runtime->services[slot - 1];
    return service->identity == instance && service->image ? service : NULL;
}
/* A single stalled native task poisons the whole runtime: reclaim nothing. */
static void require_reboot(micros_runtime_t *runtime, service_slot_t *service)
{
    runtime->usage.reboot_required = 1;
    service->state = MICROS_STATE_FAILED;
    service->result = MICROS_ERROR_REBOOT_REQUIRED;
    for (size_t slot = 0; slot < MICROS_RUNTIME_SERVICE_CAPACITY; ++slot)
        runtime->services[slot].stop_requested = 1;
    micros_platform_notify(runtime->sync);
}
static void detect_timeouts(micros_runtime_t *runtime)
{
    if (runtime->usage.reboot_required)
        return;
    uint64_t now_us = micros_platform_now_us();
    for (size_t slot = 0; slot < MICROS_RUNTIME_SERVICE_CAPACITY; ++slot) {
        service_slot_t *service = &runtime->services[slot];
        if (service->phase_active && now_us >= service->deadline_us)
            require_reboot(runtime, service);
    }
}
/* Independently watch hook deadlines, including when the management caller is
 * idle. Notification wakes the supervisor whenever a new phase is published. */
static void *supervise(void *argument)
{
    micros_runtime_t *runtime = argument;
    micros_platform_lock(runtime->sync);
    while (!runtime->shutdown) {
        detect_timeouts(runtime);
        /* One second is an idle housekeeping interval; active hooks supply
         * their precise, usually earlier deadline to the condition wait. */
        uint64_t wake_us = micros_platform_now_us() + UINT64_C(1000000);
        if (!runtime->usage.reboot_required) {
            for (size_t slot = 0; slot < MICROS_RUNTIME_SERVICE_CAPACITY; ++slot) {
                service_slot_t *service = &runtime->services[slot];
                if (service->phase_active && service->deadline_us < wake_us)
                    wake_us = service->deadline_us;
            }
        }
        micros_platform_wait(runtime->sync, wake_us);
    }
    micros_platform_unlock(runtime->sync);
    return NULL;
}
static resource_slot_t *find_resource(micros_context_t *context, micros_handle_t handle,
                                      resource_kind_t kind)
{
    uint64_t slot = handle & ID_SLOT_MASK;
    if (!slot || slot > MICROS_RUNTIME_HANDLE_CAPACITY)
        return NULL;
    resource_slot_t *resource = &context->runtime->resources[slot - 1];
    if (resource->owner != context->service->identity || resource->kind != kind ||
        identity(resource->generation, slot - 1) != handle)
        return NULL;
    return resource;
}
static micros_result_t reserve_resource(micros_context_t *context, resource_kind_t kind,
                                        micros_handle_t *handle, resource_slot_t **output)
{
    micros_runtime_t *runtime = context->runtime;
    service_slot_t *service = context->service;
    if (runtime->usage.reboot_required)
        return MICROS_ERROR_REBOOT_REQUIRED;
    if (service->stop_requested || service->state == MICROS_STATE_STOPPING || service->finished)
        return MICROS_ERROR_STATE;
    if (service->owned_handles >= service->handle_quota)
        return MICROS_ERROR_CAPACITY;
    for (size_t slot = 0; slot < MICROS_RUNTIME_HANDLE_CAPACITY; ++slot) {
        resource_slot_t *resource = &runtime->resources[slot];
        if (resource->kind != RESOURCE_FREE || !resource->generation)
            continue;
        resource->owner = service->identity;
        resource->kind = kind;
        ++service->owned_handles;
        ++runtime->usage.live_handles;
        *handle = identity(resource->generation, slot);
        *output = resource;
        return MICROS_OK;
    }
    return MICROS_ERROR_CAPACITY;
}
static void release_resource(micros_runtime_t *runtime, service_slot_t *service,
                             resource_slot_t *resource)
{
    uint32_t generation = resource->generation;
    /* Closing an old handle must not interrupt an action on a reused slot. */
    if (resource->kind == RESOURCE_SUBSCRIBER && resource->line == MICROS_COORD_ACTION &&
        resource->channel_slot < MICROS_CHANNEL_CAPACITY &&
        runtime->channels[resource->channel_slot].key &&
        runtime->channels[resource->channel_slot].generation == resource->channel_generation) {
        micros_coord_channel_t *c=runtime->coordination[resource->channel_slot];
        if (c && c->result.status==MICROS_COORD_ACCEPTED)
            c->result.status=MICROS_COORD_INDETERMINATE;
    }
    if (resource->kind == RESOURCE_GPIO) {
        micros_platform_gpio_write(runtime->gpio, resource->line, 0);
        micros_platform_gpio_release(runtime->gpio, resource->line);
    }
    memset(resource, 0, sizeof(*resource));
    if (generation == UINT32_MAX)
        ++runtime->usage.retired_handles;
    else
        resource->generation = generation + 1;
    --service->owned_handles;
    --runtime->usage.live_handles;
}
static micros_result_t api_debug(micros_context_t *context, const uint8_t *message, uint32_t bytes)
{
    if (bytes > MICROS_DEBUG_MAX_BYTES)
        return MICROS_ERROR_CAPACITY;
    if (!message && bytes)
        return MICROS_ERROR_INVALID_ARGUMENT;
    micros_platform_lock(context->runtime->sync);
    ++context->service->diagnostic_writes;
    micros_platform_unlock(context->runtime->sync);
    return micros_platform_debug(message, bytes);
}
static uint64_t api_now(micros_context_t *context)
{
    (void)context;
    return micros_platform_now_us();
}
static micros_result_t api_timer_open(micros_context_t *context, uint64_t delay_us,
                                      uint64_t period_us, micros_timer_callback_t callback,
                                      void *user_data, micros_handle_t *handle)
{
    uint64_t now_us = micros_platform_now_us();
    if (!callback || !handle || delay_us > UINT64_MAX - now_us || period_us > UINT64_MAX - now_us)
        return MICROS_ERROR_INVALID_ARGUMENT;
    micros_platform_lock(context->runtime->sync);
    if (context->service->stop_requested || context->service->state == MICROS_STATE_STOPPING) {
        micros_platform_unlock(context->runtime->sync);
        return MICROS_ERROR_STATE;
    }
    if (context->service->policy_enabled) {
        uint32_t timers = 0;
        for (size_t slot = 0; slot < MICROS_RUNTIME_HANDLE_CAPACITY; ++slot)
            if (context->runtime->resources[slot].kind == RESOURCE_TIMER &&
                context->runtime->resources[slot].owner == context->service->identity)
                ++timers;
        if (timers >= context->service->policy.timer_limit) {
            micros_platform_unlock(context->runtime->sync);
            return MICROS_ERROR_CAPACITY;
        }
    }
    resource_slot_t *resource;
    micros_result_t result = reserve_resource(context, RESOURCE_TIMER, handle, &resource);
    if (!result) {
        resource->due_us = now_us + delay_us;
        resource->period_us = period_us;
        resource->callback = callback;
        resource->user_data = user_data;
        resource->armed = 1;
        micros_platform_notify(context->runtime->sync);
    }
    micros_platform_unlock(context->runtime->sync);
    return result;
}
static micros_result_t close_resource(micros_context_t *context, micros_handle_t handle,
                                      resource_kind_t kind)
{
    micros_runtime_t *runtime = context->runtime;
    micros_platform_lock(runtime->sync);
    resource_slot_t *resource = find_resource(context, handle, kind);
    micros_result_t result = runtime->usage.reboot_required ? MICROS_ERROR_REBOOT_REQUIRED
                             : resource                     ? MICROS_OK
                                                            : MICROS_ERROR_STALE_HANDLE;
    if (!result)
        release_resource(runtime, context->service, resource);
    micros_platform_unlock(runtime->sync);
    return result;
}
static micros_result_t api_timer_close(micros_context_t *context, micros_handle_t timer)
{
    return close_resource(context, timer, RESOURCE_TIMER);
}
static micros_result_t api_gpio_close(micros_context_t *context, micros_handle_t gpio)
{
    return close_resource(context, gpio, RESOURCE_GPIO);
}
static micros_result_t api_gpio_open(micros_context_t *context, uint32_t line,
                                     micros_handle_t *handle)
{
#if MICROS_RUNTIME_GPIO_CAPACITY == 0
    (void)context;
    (void)line;
    (void)handle;
    return MICROS_ERROR_UNSUPPORTED;
#else
    if (!handle || line >= MICROS_RUNTIME_GPIO_CAPACITY)
        return MICROS_ERROR_INVALID_ARGUMENT;
    micros_runtime_t *runtime = context->runtime;
    micros_platform_lock(runtime->sync);
    micros_result_t result = context->service->policy_enabled &&
                                     !(context->service->policy.gpio_mask & (UINT32_C(1) << line))
                                 ? MICROS_ERROR_UNSUPPORTED
                                 : MICROS_OK;
    for (size_t slot = 0; slot < MICROS_RUNTIME_HANDLE_CAPACITY && !result; ++slot)
        if (runtime->resources[slot].kind == RESOURCE_GPIO && runtime->resources[slot].line == line)
            result = MICROS_ERROR_BUSY;
    if (!result) {
        resource_slot_t *resource;
        result = reserve_resource(context, RESOURCE_GPIO, handle, &resource);
        if (!result)
            resource->line = line;
    }
    micros_platform_unlock(runtime->sync);
    return result;
#endif
}
typedef enum { GPIO_READ, GPIO_WRITE, GPIO_READ_ANALOG } gpio_operation_t;
static micros_result_t gpio_access(micros_context_t *context, micros_handle_t handle,
                                   uint32_t *level, gpio_operation_t operation)
{
    if (!level || (operation == GPIO_WRITE && *level > 1))
        return MICROS_ERROR_INVALID_ARGUMENT;
    micros_runtime_t *runtime = context->runtime;
    micros_platform_lock(runtime->sync);
    resource_slot_t *resource = find_resource(context, handle, RESOURCE_GPIO);
    micros_result_t result = runtime->usage.reboot_required ? MICROS_ERROR_REBOOT_REQUIRED
                             : resource                     ? MICROS_OK
                                                            : MICROS_ERROR_STALE_HANDLE;
    if (!result) {
        if (operation == GPIO_READ_ANALOG)
            result = micros_platform_gpio_read_analog(runtime->gpio, resource->line, level);
        else if (operation == GPIO_WRITE)
            result = micros_platform_gpio_write(runtime->gpio, resource->line, *level);
        else
            result = micros_platform_gpio_read(runtime->gpio, resource->line, level);
    }
    micros_platform_unlock(runtime->sync);
    return result;
}
static micros_result_t api_gpio_read(micros_context_t *context, micros_handle_t gpio,
                                     uint32_t *level)
{
    return gpio_access(context, gpio, level, GPIO_READ);
}
static micros_result_t api_gpio_write(micros_context_t *context, micros_handle_t gpio,
                                      uint32_t level)
{
    return gpio_access(context, gpio, &level, GPIO_WRITE);
}
static micros_result_t api_gpio_read_analog(micros_context_t *context, micros_handle_t gpio,
                                           uint32_t *raw)
{
    return gpio_access(context, gpio, raw, GPIO_READ_ANALOG);
}
static micros_result_t api_ipc_open(micros_context_t *context, uint32_t key, uint32_t access,
                                    micros_handle_t *handle)
{
    if (!handle || (access != MICROS_IPC_PUBLISH && access != MICROS_IPC_SUBSCRIBE))
        return MICROS_ERROR_INVALID_ARGUMENT;
    micros_runtime_t *runtime = context->runtime;
    micros_platform_lock(runtime->sync);
    if (context->service->policy_enabled) {
        uint32_t allowed = access == MICROS_IPC_PUBLISH ? context->service->policy.publish_mask
                                                        : context->service->policy.subscribe_mask;
        /* One bit per key in the manifest profile; avoid shifts outside uint32. */
        if (!key || key > 32 || !(allowed & (UINT32_C(1) << (key - 1)))) {
            micros_platform_unlock(runtime->sync);
            return MICROS_ERROR_UNSUPPORTED;
        }
    }
    micros_result_t result = MICROS_ERROR_INVALID_ARGUMENT;
    for (size_t slot = 0; slot < MICROS_CHANNEL_CAPACITY; ++slot) {
        micros_channel_t *channel = &runtime->channels[slot];
        if (!key || channel->key != key)
            continue;
        resource_slot_t *resource;
        result = reserve_resource(
            context, access == MICROS_IPC_PUBLISH ? RESOURCE_PUBLISHER : RESOURCE_SUBSCRIBER,
            handle, &resource);
        if (!result) {
            resource->channel_slot = (uint32_t)slot;
            resource->channel_generation = channel->generation;
            resource->next_sequence =
                channel->policy == MICROS_CHANNEL_LATEST && channel->sequence ? channel->sequence
                : channel->sequence >= channel->depth ? channel->sequence - channel->depth + 1
                                                      : 1;
        }
        break;
    }
    micros_platform_unlock(runtime->sync);
    return result;
}
static micros_channel_t *resource_channel(micros_runtime_t *runtime, resource_slot_t *resource)
{
    if (!resource)
        return NULL;
    micros_channel_t *channel = &runtime->channels[resource->channel_slot];
    return channel->key && channel->generation == resource->channel_generation ? channel : NULL;
}
static micros_result_t api_ipc_publish(micros_context_t *context, micros_handle_t handle,
                                       const uint8_t *payload, uint32_t payload_bytes)
{
    micros_runtime_t *runtime = context->runtime;
    micros_platform_lock(runtime->sync);
    resource_slot_t *resource = find_resource(context, handle, RESOURCE_PUBLISHER);
    micros_channel_t *channel = resource_channel(runtime, resource);
    micros_result_t result =
        runtime->usage.reboot_required ? MICROS_ERROR_REBOOT_REQUIRED
        : !channel                     ? MICROS_ERROR_STALE_HANDLE
        : context->service->stop_requested || context->service->state == MICROS_STATE_STOPPING
            ? MICROS_ERROR_STATE
            : MICROS_OK;
    if (!result && (runtime->coordination[resource->channel_slot] && runtime->coordination[resource->channel_slot]->kind)) result=MICROS_ERROR_UNSUPPORTED;
    if (!result) {
        result = micros_channel_publish(channel, payload, payload_bytes);
        if (!result) {
            runtime->channel_last_us[resource->channel_slot] = micros_platform_now_us();
            micros_platform_notify(runtime->sync);
        }
    }
    micros_platform_unlock(runtime->sync);
    return result;
}
static micros_result_t api_ipc_read(micros_context_t *context, micros_handle_t handle,
                                    uint8_t *output, uint32_t capacity, uint32_t *output_bytes,
                                    micros_message_info_t *info)
{
    micros_runtime_t *runtime = context->runtime;
    micros_platform_lock(runtime->sync);
    resource_slot_t *resource = find_resource(context, handle, RESOURCE_SUBSCRIBER);
    micros_channel_t *channel = resource_channel(runtime, resource);
    micros_result_t result = runtime->usage.reboot_required ? MICROS_ERROR_REBOOT_REQUIRED
                             : !channel                     ? MICROS_ERROR_STALE_HANDLE
                                                            : MICROS_OK;
    if (!result && (runtime->coordination[resource->channel_slot] && runtime->coordination[resource->channel_slot]->kind)) result=MICROS_ERROR_UNSUPPORTED;
    if (!result) {
        result = micros_channel_read(channel, &resource->next_sequence, output, capacity,
                                     output_bytes, info);
        /* A loss report advances without delivering a payload. */
        if (result == MICROS_ERROR_MESSAGES_MISSED || result == MICROS_OK)
            runtime->channel_missed[resource->channel_slot] += info->messages_missed;
    }
    micros_platform_unlock(runtime->sync);
    return result;
}
static micros_result_t api_ipc_close(micros_context_t *context, micros_handle_t handle)
{
    micros_result_t result = close_resource(context, handle, RESOURCE_PUBLISHER);
    return result == MICROS_ERROR_STALE_HANDLE
               ? close_resource(context, handle, RESOURCE_SUBSCRIBER)
               : result;
}
#include "coordination.inc"
/* Exported dispatch also identifies bases supporting generated IPC bindings. */
const struct micros_ipc_api micros_runtime_ipc_api = {
    .ipc_open = api_ipc_open,
    .ipc_publish = api_ipc_publish,
    .ipc_read = api_ipc_read,
    .ipc_close = api_ipc_close,
    .coord_open = api_coord_open,
    .coord = api_coord,
};

static const micros_api_t runtime_api = {.struct_bytes = sizeof(micros_api_t),
                                         .abi_major = MICROS_ABI_MAJOR,
                                         .abi_revision = MICROS_ABI_REVISION,
                                         .debug_write = api_debug,
                                         .monotonic_us = api_now,
                                         .timer_open = api_timer_open,
                                         .timer_close = api_timer_close,
                                         .gpio_open = api_gpio_open,
                                         .gpio_read = api_gpio_read,
                                         .gpio_write = api_gpio_write,
                                         .gpio_close = api_gpio_close,
                                         ._ipc = &micros_runtime_ipc_api,
                                         .gpio_read_analog = api_gpio_read_analog};

/* Invoked with the coordination lock held; native code always runs without it. */
static micros_result_t invoke_hook(service_slot_t *service, micros_service_hook_t hook,
                                   uint64_t budget_us)
{
    micros_runtime_t *runtime = service->context.runtime;
    while (runtime->paused && !runtime->usage.reboot_required)
        micros_platform_wait(runtime->sync, micros_platform_now_us() + UINT64_C(10000));
    if (runtime->usage.reboot_required) return MICROS_ERROR_REBOOT_REQUIRED;
    uint64_t started_us = micros_platform_now_us();
    service->deadline_us = started_us + budget_us;
    service->phase_active = 1;
    micros_platform_notify(runtime->sync);
    micros_platform_unlock(runtime->sync);
    micros_result_t result = hook(&service->args);
    micros_platform_lock(runtime->sync);
    uint64_t elapsed_us = micros_platform_now_us() - started_us;
    if (elapsed_us > service->hook_max_us) service->hook_max_us = elapsed_us;
    detect_timeouts(runtime);
    service->phase_active = 0;
    micros_platform_notify(runtime->sync);
    return runtime->usage.reboot_required ? MICROS_ERROR_REBOOT_REQUIRED : result;
}
static void record_failure(service_slot_t *service, micros_result_t result)
{
    if (!service->result)
        service->result = result;
}
static void *service_worker(void *argument)
{
    service_slot_t *service = argument;
    micros_runtime_t *runtime = service->context.runtime;
    micros_platform_lock(runtime->sync);
    record_failure(service, invoke_hook(service, service->descriptor->init,
                                        runtime->config.lifecycle_timeout_us));
    if (!service->result && !service->stop_requested) {
        service->state = MICROS_STATE_STARTING;
        record_failure(service, invoke_hook(service, service->descriptor->start,
                                            runtime->config.lifecycle_timeout_us));
    }
    if (!service->result && !service->stop_requested)
        service->state = MICROS_STATE_RUNNING;
    uint64_t next_step_us = micros_platform_now_us();
    while (!service->result && !service->stop_requested && !runtime->usage.reboot_required) {
        uint64_t now_us = micros_platform_now_us();
        if (now_us >= next_step_us) {
            micros_result_t result =
                invoke_hook(service, service->descriptor->step, runtime->config.work_timeout_us);
            ++service->completed_steps;
            record_failure(service, result);
            next_step_us = micros_platform_now_us() + runtime->config.step_interval_us;
        }
        /* Scan each admitted timer at most once per pass: overdue periodic work
         * is coalesced, and even self-rearming callbacks cannot starve steps. */
        uint64_t wake_us = next_step_us;
        for (size_t slot = 0; slot < MICROS_RUNTIME_HANDLE_CAPACITY && !service->result &&
                              !service->stop_requested && !runtime->usage.reboot_required;
             ++slot) {
            resource_slot_t *resource = &runtime->resources[slot];
            if (resource->owner != service->identity || resource->kind != RESOURCE_TIMER ||
                !resource->armed)
                continue;
            now_us = micros_platform_now_us();
            if (resource->due_us <= now_us) {
                while (runtime->paused && !runtime->usage.reboot_required)
                    micros_platform_wait(runtime->sync, micros_platform_now_us() + UINT64_C(10000));
                if (runtime->usage.reboot_required) break;
                now_us = micros_platform_now_us();
                uint64_t late_us = now_us - resource->due_us;
                if (late_us > service->timer_late_max_us) service->timer_late_max_us = late_us;
                micros_timer_callback_t callback = resource->callback;
                void *user_data = resource->user_data;
                micros_handle_t handle = identity(resource->generation, slot);
                resource->armed = resource->period_us && resource->period_us <= UINT64_MAX - now_us;
                if (resource->armed)
                    resource->due_us = now_us + resource->period_us;
                service->phase_active = 1;
                service->deadline_us = now_us + runtime->config.work_timeout_us;
                ++runtime->usage.active_callbacks;
                micros_platform_notify(runtime->sync);
                micros_platform_unlock(runtime->sync);
                micros_result_t result = callback(&service->args, handle, user_data);
                micros_platform_lock(runtime->sync);
                uint64_t elapsed_us = micros_platform_now_us() - now_us;
                if (elapsed_us > service->callback_max_us) service->callback_max_us = elapsed_us;
                detect_timeouts(runtime);
                service->phase_active = 0;
                micros_platform_notify(runtime->sync);
                --runtime->usage.active_callbacks;
                ++service->completed_callbacks;
                record_failure(service, result);
            }
            /* Callback may have closed/replaced this slot; recheck ownership. */
            if (resource->owner == service->identity && resource->kind == RESOURCE_TIMER &&
                resource->armed && resource->due_us < wake_us)
                wake_us = resource->due_us;
        }
        if (!service->result && !service->stop_requested && !runtime->usage.reboot_required)
            micros_platform_wait(runtime->sync, wake_us);
    }
    if (!runtime->usage.reboot_required) {
        service->state = MICROS_STATE_STOPPING;
        record_failure(service, invoke_hook(service, service->descriptor->stop,
                                            runtime->config.lifecycle_timeout_us));
    }
    if (!runtime->usage.reboot_required) {
        /* No callback source has its own thread: stop and all callbacks have
         * returned on this worker, so ownership cleanup cannot race execution. */
        for (size_t slot = 0; slot < MICROS_RUNTIME_HANDLE_CAPACITY; ++slot)
            if (runtime->resources[slot].owner == service->identity)
                release_resource(runtime, service, &runtime->resources[slot]);
        service->state = service->result ? MICROS_STATE_FAILED : MICROS_STATE_STOPPED;
    } else {
        service->state = MICROS_STATE_FAILED;
        service->result = MICROS_ERROR_REBOOT_REQUIRED;
    }
    service->finished = 1;
    micros_platform_notify(runtime->sync);
    micros_platform_unlock(runtime->sync);
    return NULL;
}

micros_runtime_config_t micros_runtime_default_config(void)
{
    /* Admit four M1-sized arenas/stacks and up to four bounded native payloads.
     * Host stack reservations use the BSP floor separately from requested bytes. */
    return (micros_runtime_config_t){
        .image_bytes = (size_t)MICROS_IMAGE_LIMIT * MICROS_RUNTIME_SERVICE_CAPACITY,
        .arena_bytes = MICROS_M1_ARENA_BYTES * MICROS_RUNTIME_SERVICE_CAPACITY,
        .stack_bytes = MICROS_M1_MAX_STACK_BYTES * MICROS_RUNTIME_SERVICE_CAPACITY,
        .platform_stack_bytes = micros_platform_stack_bytes(MICROS_M1_MAX_STACK_BYTES) *
                                MICROS_RUNTIME_SERVICE_CAPACITY,
        .handle_count = MICROS_RUNTIME_HANDLE_CAPACITY,
        .channel_bytes = MICROS_CHANNEL_POOL_BYTES,
        .lifecycle_timeout_us = MICROS_M1_LIFECYCLE_TIMEOUT_MS * US_PER_MS,
        .work_timeout_us = DEFAULT_WORK_TIMEOUT_US,
        .step_interval_us = MICROS_M1_STEP_DELAY_MS * US_PER_MS};
}
micros_runtime_t *micros_runtime_create(const micros_runtime_config_t *config)
{
    /* Bound policy durations to one minute so deadline additions cannot overflow
     * and accidental unit errors cannot disable useful failure detection. */
    const uint64_t maximum_policy_us = UINT64_C(60) * 1000 * US_PER_MS;
    if (!config || config->handle_count > MICROS_RUNTIME_HANDLE_CAPACITY ||
        !config->lifecycle_timeout_us || config->lifecycle_timeout_us > maximum_policy_us ||
        !config->work_timeout_us || config->work_timeout_us > maximum_policy_us ||
        !config->step_interval_us || config->step_interval_us > maximum_policy_us)
        return NULL;
    micros_runtime_t *runtime = runtime_allocate();
    if (!runtime)
        return NULL;
    runtime->config = *config;
    for (size_t slot = 0; slot < MICROS_CHANNEL_CAPACITY; ++slot)
        runtime->channels[slot].generation = 1;
    runtime->sync = micros_platform_sync_create();
    if (!runtime->sync) {
        runtime_release(runtime);
        return NULL;
    }
    runtime->gpio = micros_platform_gpio_create(MICROS_RUNTIME_GPIO_CAPACITY);
    if (!runtime->gpio) {
        micros_platform_sync_destroy(runtime->sync);
        runtime_release(runtime);
        return NULL;
    }
    for (size_t slot = 0; slot < MICROS_RUNTIME_SERVICE_CAPACITY; ++slot)
        runtime->services[slot].generation = 1;
    for (size_t slot = 0; slot < MICROS_RUNTIME_HANDLE_CAPACITY; ++slot)
        runtime->resources[slot].generation = 1;
    runtime->usage.supervisor_stack_bytes = micros_platform_stack_bytes(
        config->supervisor_stack_bytes ? config->supervisor_stack_bytes : MICROS_M1_STACK_BYTES);
    runtime->usage.kernel_metadata_bytes =
        sizeof(*runtime) + micros_platform_metadata_bytes(MICROS_RUNTIME_GPIO_CAPACITY) +
        micros_platform_task_metadata_bytes();
    runtime->supervisor = micros_platform_supervisor_create(supervise, runtime,
                                                            runtime->usage.supervisor_stack_bytes);
    if (!runtime->supervisor) {
        micros_platform_gpio_destroy(runtime->gpio);
        micros_platform_sync_destroy(runtime->sync);
        runtime_release(runtime);
        return NULL;
    }
    return runtime;
}
micros_result_t micros_runtime_destroy(micros_runtime_t *runtime)
{
    if (!runtime)
        return MICROS_ERROR_INVALID_ARGUMENT;
    micros_platform_lock(runtime->sync);
    micros_result_t result = runtime->usage.reboot_required   ? MICROS_ERROR_REBOOT_REQUIRED
                             : runtime->usage.loaded_services ? MICROS_ERROR_STATE
                                                              : MICROS_OK;
    if (!result) {
        runtime->shutdown = 1;
        micros_platform_notify(runtime->sync);
    }
    micros_platform_unlock(runtime->sync);
    if (!result) {
        micros_platform_task_join(runtime->supervisor);
        for (size_t slot = 0; slot < MICROS_CHANNEL_CAPACITY; ++slot) {
            micros_platform_arena_free(runtime->channels[slot].payload);
            micros_memory_free(runtime->coordination[slot]);
        }
        micros_platform_gpio_destroy(runtime->gpio);
        micros_platform_sync_destroy(runtime->sync);
        runtime_release(runtime);
    }
    return result;
}
static int fits(size_t used, size_t request, size_t limit)
{
    return used <= limit && request <= limit - used;
}
micros_result_t micros_runtime_load(micros_runtime_t *runtime, const char *path,
                                    uint32_t handle_quota, micros_instance_t *instance)
{
    if (!runtime || !path || !instance)
        return MICROS_ERROR_INVALID_ARGUMENT;
    if (handle_quota > MICROS_RUNTIME_HANDLES_PER_SERVICE)
        return MICROS_ERROR_CAPACITY;
    micros_platform_lock(runtime->sync);
    detect_timeouts(runtime);
    if (runtime->usage.reboot_required) {
        micros_platform_unlock(runtime->sync);
        return MICROS_ERROR_REBOOT_REQUIRED;
    }
    service_slot_t *service = NULL;
    for (size_t slot = 0; slot < MICROS_RUNTIME_SERVICE_CAPACITY; ++slot)
        if (!runtime->services[slot].image && runtime->services[slot].generation) {
            service = &runtime->services[slot];
            break;
        }
    if (!service) {
        micros_platform_unlock(runtime->sync);
        return MICROS_ERROR_CAPACITY;
    }
    /* The management API is single-controller. Release the lock around I/O so
     * existing service callbacks and deadlines remain independently observable. */
    micros_platform_unlock(runtime->sync);
    micros_platform_image_t *image;
    const micros_service_descriptor_t *descriptor;
    size_t image_bytes;
    micros_result_t result = micros_platform_image_open(path, &image, &descriptor, &image_bytes);
    if (result)
        return result;
    size_t platform_stack_bytes = micros_platform_stack_bytes(descriptor->stack_bytes);
    micros_platform_lock(runtime->sync);
    detect_timeouts(runtime);
    if (runtime->usage.reboot_required)
        result = MICROS_ERROR_REBOOT_REQUIRED;
    else if (!fits(runtime->usage.image_bytes, image_bytes, runtime->config.image_bytes) ||
             !fits(runtime->usage.arena_bytes, descriptor->arena_bytes,
                   runtime->config.arena_bytes) ||
             !fits(runtime->usage.stack_bytes, descriptor->stack_bytes,
                   runtime->config.stack_bytes) ||
             !fits(runtime->usage.platform_stack_bytes, platform_stack_bytes,
                   runtime->config.platform_stack_bytes) ||
             !fits(runtime->usage.reserved_handles, handle_quota, runtime->config.handle_count) ||
             !fits(runtime->usage.reserved_handles, handle_quota,
                   MICROS_RUNTIME_HANDLE_CAPACITY - runtime->usage.retired_handles))
        result = MICROS_ERROR_CAPACITY;
    void *arena = NULL;
    size_t alignment =
        descriptor->arena_alignment < sizeof(void *) ? sizeof(void *) : descriptor->arena_alignment;
    /* C17 aligned_alloc requires an integral number of alignment units. */
    size_t arena_storage_bytes = descriptor->arena_bytes ? descriptor->arena_bytes : alignment;
    arena_storage_bytes = (arena_storage_bytes + alignment - 1) / alignment * alignment;
    if (!result && !(arena = micros_platform_arena_allocate(alignment, arena_storage_bytes, descriptor->reserved)))
        result = MICROS_ERROR_CAPACITY;
#ifdef MICROS_STATIC_MEMORY
    void *stack_storage = !result ? micros_memory_allocate(platform_stack_bytes) : NULL;
    if (!result && !stack_storage) {
        micros_platform_arena_free(arena);
        result = MICROS_ERROR_CAPACITY;
    }
#endif
    if (result) {
        micros_platform_unlock(runtime->sync);
        micros_platform_image_close(image);
        return result;
    }
    memset(arena, 0, arena_storage_bytes);
    service->identity = identity(service->generation, (size_t)(service - runtime->services));
    service->state = MICROS_STATE_LOADED;
    service->image = image;
    service->descriptor = descriptor;
    service->context = (micros_context_t){runtime, service};
    service->args = (micros_service_args_t){sizeof(micros_service_args_t), descriptor->arena_bytes,
                                            &service->context, &runtime_api, arena, NULL, 0};
    service->image_bytes = image_bytes;
    service->platform_stack_bytes = platform_stack_bytes;
#ifdef MICROS_STATIC_MEMORY
    service->stack_storage = stack_storage;
#endif
    service->arena_storage_bytes = arena_storage_bytes;
    runtime->usage.arena_storage_bytes += arena_storage_bytes;
    service->handle_quota = handle_quota;
    runtime->usage.image_bytes += image_bytes;
    runtime->usage.arena_bytes += descriptor->arena_bytes;
    runtime->usage.stack_bytes += descriptor->stack_bytes;
    runtime->usage.platform_stack_bytes += platform_stack_bytes;
    runtime->usage.reserved_handles += handle_quota;
    ++runtime->usage.loaded_services;
    *instance = service->identity;
    micros_platform_unlock(runtime->sync);
    return MICROS_OK;
}
micros_result_t micros_runtime_set_config(micros_runtime_t *runtime, micros_instance_t instance,
                                          const uint8_t *data, uint32_t bytes)
{
    if (!runtime || bytes > MICROS_CONFIG_MAX_BYTES || (bytes && !data))
        return MICROS_ERROR_INVALID_ARGUMENT;
    micros_platform_lock(runtime->sync);
    service_slot_t *service = find_service(runtime, instance);
    if (!service || service->state != MICROS_STATE_LOADED) {
        micros_platform_unlock(runtime->sync);
        return MICROS_ERROR_INVALID_ARGUMENT;
    }
    /* Configuration is immutable once started. Reserve only the admitted
     * bytes, rather than four maximum-size records in every empty runtime. */
    uint8_t *copy = bytes ? micros_memory_allocate(bytes) : NULL;
    if (bytes && !copy) {
        micros_platform_unlock(runtime->sync);
        return MICROS_ERROR_CAPACITY;
    }
    if (bytes) memcpy(copy, data, bytes);
    runtime->usage.kernel_metadata_bytes -= service->args.config_bytes;
    runtime->usage.kernel_metadata_bytes += bytes;
    micros_memory_free(service->config_data);
    service->config_data = copy;
    service->args.config_data = copy;
    service->args.config_bytes = bytes;
    micros_platform_unlock(runtime->sync);
    return MICROS_OK;
}

micros_result_t micros_runtime_set_policy(micros_runtime_t *runtime, micros_instance_t instance,
                                          const micros_resource_policy_t *policy)
{
    if (!runtime || !policy || policy->timer_limit > MICROS_RUNTIME_HANDLES_PER_SERVICE ||
        policy->gpio_mask >= (UINT32_C(1) << MICROS_RUNTIME_GPIO_CAPACITY))
        return MICROS_ERROR_INVALID_ARGUMENT;
    micros_platform_lock(runtime->sync);
    service_slot_t *service = find_service(runtime, instance);
    micros_result_t result = runtime->usage.reboot_required ? MICROS_ERROR_REBOOT_REQUIRED
                             : !service                     ? MICROS_ERROR_STALE_HANDLE
                             : service->state != MICROS_STATE_LOADED || service->owned_handles
                                 ? MICROS_ERROR_STATE
                                 : MICROS_OK;
    if (!result) {
        service->policy = *policy;
        service->policy_enabled = 1;
    }
    micros_platform_unlock(runtime->sync);
    return result;
}
micros_result_t micros_runtime_start(micros_runtime_t *runtime, micros_instance_t instance)
{
    if (!runtime)
        return MICROS_ERROR_INVALID_ARGUMENT;
    micros_platform_lock(runtime->sync);
    detect_timeouts(runtime);
    service_slot_t *service = find_service(runtime, instance);
    micros_result_t result = runtime->usage.reboot_required          ? MICROS_ERROR_REBOOT_REQUIRED
                             : !service                              ? MICROS_ERROR_STALE_HANDLE
                             : service->state != MICROS_STATE_LOADED ? MICROS_ERROR_STATE
                                                                     : MICROS_OK;
    if (!result) {
        service->state = MICROS_STATE_INITIALIZING;
#ifdef MICROS_STATIC_MEMORY
        service->task = micros_platform_task_create_with_stack(service_worker, service,
            service->platform_stack_bytes, service->stack_storage);
#else
        service->task =
            micros_platform_task_create(service_worker, service, service->platform_stack_bytes);
#endif
        if (!service->task) {
            service->state = MICROS_STATE_LOADED;
            result = MICROS_ERROR_CAPACITY;
        } else {
            ++runtime->usage.live_tasks;
            runtime->usage.kernel_metadata_bytes += micros_platform_task_metadata_bytes();
        }
    }
    micros_platform_unlock(runtime->sync);
    return result;
}
micros_result_t micros_runtime_stop(micros_runtime_t *runtime, micros_instance_t instance)
{
    if (!runtime)
        return MICROS_ERROR_INVALID_ARGUMENT;
    micros_platform_lock(runtime->sync);
    detect_timeouts(runtime);
    service_slot_t *service = find_service(runtime, instance);
    if (!service || runtime->usage.reboot_required) {
        micros_result_t result = runtime->usage.reboot_required ? MICROS_ERROR_REBOOT_REQUIRED
                                                                : MICROS_ERROR_STALE_HANDLE;
        micros_platform_unlock(runtime->sync);
        return result;
    }
    if (!service->task) {
        micros_result_t result = service->result;
        micros_platform_unlock(runtime->sync);
        return result;
    }
    service->stop_requested = 1;
    micros_platform_notify(runtime->sync);
    /* Allow the current lifecycle/work hook and then one stop hook, while each
     * individual hook retains its own stricter deadline. This also bounds an
     * unexpectedly unscheduled worker that has not entered its next hook. */
    uint64_t stop_deadline_us = micros_platform_now_us() +
                                runtime->config.lifecycle_timeout_us * 2 +
                                runtime->config.work_timeout_us;
    while (!service->finished && !runtime->usage.reboot_required) {
        detect_timeouts(runtime);
        if (micros_platform_now_us() >= stop_deadline_us)
            require_reboot(runtime, service);
        if (runtime->usage.reboot_required)
            break;
        uint64_t wake_us = service->phase_active && service->deadline_us < stop_deadline_us
                               ? service->deadline_us
                               : stop_deadline_us;
        micros_platform_wait(runtime->sync, wake_us);
    }
    if (runtime->usage.reboot_required) {
        micros_platform_unlock(runtime->sync);
        return MICROS_ERROR_REBOOT_REQUIRED;
    }
    micros_platform_task_t *task = service->task;
    micros_platform_unlock(runtime->sync);
    micros_platform_task_join(task);
    micros_platform_lock(runtime->sync);
    service->task = NULL;
    --runtime->usage.live_tasks;
    runtime->usage.kernel_metadata_bytes -= micros_platform_task_metadata_bytes();
    micros_result_t result = service->result;
    micros_platform_unlock(runtime->sync);
    return result;
}
micros_result_t micros_runtime_unload(micros_runtime_t *runtime, micros_instance_t instance)
{
    if (!runtime)
        return MICROS_ERROR_INVALID_ARGUMENT;
    micros_platform_lock(runtime->sync);
    detect_timeouts(runtime);
    service_slot_t *service = find_service(runtime, instance);
    micros_result_t result = runtime->usage.reboot_required ? MICROS_ERROR_REBOOT_REQUIRED
                             : !service                     ? MICROS_ERROR_STALE_HANDLE
                             : service->task || service->owned_handles ? MICROS_ERROR_STATE
                                                                       : MICROS_OK;
    if (result) {
        micros_platform_unlock(runtime->sync);
        return result;
    }
    runtime->usage.image_bytes -= service->image_bytes;
    runtime->usage.arena_storage_bytes -= service->arena_storage_bytes;
    runtime->usage.arena_bytes -= service->descriptor->arena_bytes;
    runtime->usage.stack_bytes -= service->descriptor->stack_bytes;
    runtime->usage.platform_stack_bytes -= service->platform_stack_bytes;
    runtime->usage.reserved_handles -= service->handle_quota;
    --runtime->usage.loaded_services;
    micros_platform_image_t *image = service->image;
    void *arena = service->args.arena;
    uint8_t *configuration = service->config_data;
#ifdef MICROS_STATIC_MEMORY
    micros_memory_free(service->stack_storage);
#endif
    runtime->usage.kernel_metadata_bytes -= service->args.config_bytes;
    uint32_t generation = service->generation;
    memset(service, 0, sizeof(*service));
    if (generation == UINT32_MAX)
        ++runtime->usage.retired_services;
    else
        service->generation = generation + 1;
    micros_platform_unlock(runtime->sync);
    micros_memory_free(configuration);
    micros_platform_arena_free(arena);
    micros_platform_image_close(image);
    return MICROS_OK;
}
micros_result_t micros_runtime_pause(micros_runtime_t *runtime)
{
    if (!runtime) return MICROS_ERROR_INVALID_ARGUMENT;
    micros_platform_lock(runtime->sync);
    if (runtime->paused) {
        micros_platform_unlock(runtime->sync);
        return MICROS_ERROR_STATE;
    }
    runtime->paused = 1;
    for (;;) {
        detect_timeouts(runtime);
        int active = 0;
        for (unsigned i = 0; i < MICROS_RUNTIME_SERVICE_CAPACITY; ++i)
            active |= runtime->services[i].phase_active;
        if (!active || runtime->usage.reboot_required) break;
        micros_platform_wait(runtime->sync, micros_platform_now_us() + UINT64_C(1000));
    }
    micros_result_t result = runtime->usage.reboot_required ? MICROS_ERROR_REBOOT_REQUIRED : MICROS_OK;
    if (result) runtime->paused = 0;
    micros_platform_unlock(runtime->sync);
    return result;
}
void micros_runtime_resume(micros_runtime_t *runtime)
{
    if (!runtime) return;
    micros_platform_lock(runtime->sync);
    runtime->paused = 0;
    micros_platform_notify(runtime->sync);
    micros_platform_unlock(runtime->sync);
}

micros_result_t micros_runtime_restart(micros_runtime_t *runtime, micros_instance_t *instance,
                                      const char *image_path, uint32_t handle_quota,
                                      const micros_resource_policy_t *policy,
                                      const uint8_t *configuration, uint32_t configuration_bytes)
{
    if (!runtime || !instance || !image_path || !policy ||
        handle_quota > MICROS_RUNTIME_HANDLES_PER_SERVICE ||
        configuration_bytes > MICROS_CONFIG_MAX_BYTES ||
        (configuration_bytes && !configuration))
        return MICROS_ERROR_INVALID_ARGUMENT;
    if (*instance) {
        /* A completed service failure is recoverable. Unload is the authority
         * for quiescence: it rejects outstanding tasks/handles and timeouts. */
        micros_runtime_stop(runtime, *instance);
        micros_result_t result = micros_runtime_unload(runtime, *instance);
        if (result) return result;
        *instance = 0;
    }
    micros_result_t result = micros_runtime_load(runtime, image_path, handle_quota, instance);
    if (!result) result = micros_runtime_set_config(runtime, *instance, configuration, configuration_bytes);
    if (!result) result = micros_runtime_set_policy(runtime, *instance, policy);
    if (!result) result = micros_runtime_start(runtime, *instance);
    return result;
}

micros_result_t micros_runtime_status(micros_runtime_t *runtime, micros_instance_t instance,
                                      micros_service_status_t *status)
{
    if (!runtime || !status)
        return MICROS_ERROR_INVALID_ARGUMENT;
    micros_platform_lock(runtime->sync);
    detect_timeouts(runtime);
    service_slot_t *service = find_service(runtime, instance);
    if (service) {
        *status = (micros_service_status_t){
            service->state,
            service->result,
            service->owned_handles,
            service->diagnostic_writes,
            service->completed_steps,
            service->completed_callbacks,
            runtime->usage.reboot_required,
            service->descriptor->arena_bytes,
            service->descriptor->arena_alignment,
            service->descriptor->stack_bytes,
            service->task ? micros_platform_stack_free(service->task) : 0,
            service->handle_quota, service->policy.timer_limit, 0, service->policy.gpio_mask, 0,
            service->policy.publish_mask, service->policy.subscribe_mask,
            service->hook_max_us, service->callback_max_us, service->timer_late_max_us, service->descriptor->reserved};
        for (size_t slot = 0; slot < MICROS_RUNTIME_HANDLE_CAPACITY; ++slot) {
            resource_slot_t *resource = &runtime->resources[slot];
            if (resource->owner != instance) continue;
            if (resource->kind == RESOURCE_TIMER) ++status->timers_open;
            if (resource->kind == RESOURCE_GPIO) status->gpio_open |= UINT32_C(1) << resource->line;
        }
    }
    micros_platform_unlock(runtime->sync);
    return service ? MICROS_OK : MICROS_ERROR_STALE_HANDLE;
}
micros_result_t micros_runtime_channel_create(micros_runtime_t *runtime, uint32_t key,
                                              uint32_t policy, uint32_t depth,
                                              uint32_t payload_bytes)
{
    if (!runtime || !key || (policy != MICROS_CHANNEL_STREAM && policy != MICROS_CHANNEL_LATEST) ||
        !depth || depth > MICROS_CHANNEL_MAX_DEPTH || !payload_bytes ||
        payload_bytes > MICROS_CHANNEL_MAX_PAYLOAD ||
        (policy == MICROS_CHANNEL_LATEST && depth != 1))
        return MICROS_ERROR_INVALID_ARGUMENT;
    micros_platform_lock(runtime->sync);
    detect_timeouts(runtime);
    micros_result_t result =
        runtime->usage.reboot_required ? MICROS_ERROR_REBOOT_REQUIRED : MICROS_OK;
    micros_channel_t *available = NULL;
    for (size_t slot = 0; slot < MICROS_CHANNEL_CAPACITY; ++slot) {
        micros_channel_t *channel = &runtime->channels[slot];
        if (channel->key == key)
            result = MICROS_ERROR_BUSY;
        if (!channel->key && channel->generation && !available)
            available = channel;
    }
    size_t bytes = (size_t)depth * payload_bytes;
    if (!result &&
        (!available || !fits(runtime->usage.channel_bytes, bytes, runtime->config.channel_bytes)))
        result = MICROS_ERROR_CAPACITY;
    /* Ordinary protobuf channels need only payload storage. Coordination state
     * is charged to the bounded application pool when a coordination port opens. */
    const size_t alignment = _Alignof(micros_coord_channel_t);
    size_t payload_bytes_aligned = (bytes + alignment - 1) / alignment * alignment;
    size_t storage_bytes = payload_bytes_aligned;
    uint8_t *payload = NULL;
    if (!result && !(payload = micros_platform_arena_allocate(alignment, storage_bytes, 0)))
        result = MICROS_ERROR_CAPACITY;
    if (!result) {
        available->payload = payload;
        runtime->coordination[available-runtime->channels] = NULL;
        runtime->channel_missed[available-runtime->channels] = 0;
        runtime->channel_last_us[available-runtime->channels] = 0;
        available->key = key;
        available->policy = policy;
        available->depth = depth;
        available->payload_bytes = payload_bytes;
        ++runtime->usage.channels;
        runtime->usage.channel_bytes += bytes;
    }
    micros_platform_unlock(runtime->sync);
    return result;
}
micros_result_t micros_runtime_channel_destroy(micros_runtime_t *runtime, uint32_t key)
{
    if (!runtime || !key)
        return MICROS_ERROR_INVALID_ARGUMENT;
    micros_platform_lock(runtime->sync);
    detect_timeouts(runtime);
    if (runtime->usage.reboot_required) {
        micros_platform_unlock(runtime->sync);
        return MICROS_ERROR_REBOOT_REQUIRED;
    }
    micros_result_t result = MICROS_ERROR_INVALID_ARGUMENT;
    for (size_t slot = 0; slot < MICROS_CHANNEL_CAPACITY; ++slot) {
        micros_channel_t *channel = &runtime->channels[slot];
        if (channel->key != key)
            continue;
        runtime->usage.channel_bytes -= (size_t)channel->depth * channel->payload_bytes;
        --runtime->usage.channels;
        uint32_t generation = channel->generation;
        micros_platform_arena_free(channel->payload);
        memset(channel, 0, sizeof(*channel));
        micros_memory_free(runtime->coordination[slot]);
        runtime->coordination[slot] = NULL;
        channel->generation = generation == UINT32_MAX ? 0 : generation + 1;
        result = MICROS_OK;
        break;
    }
    micros_platform_notify(runtime->sync);
    micros_platform_unlock(runtime->sync);
    return result;
}
micros_runtime_usage_t micros_runtime_usage(micros_runtime_t *runtime)
{
    micros_platform_lock(runtime->sync);
    detect_timeouts(runtime);
    micros_runtime_usage_t usage = runtime->usage;
    size_t payload_storage = 0;
    for (size_t slot = 0; slot < MICROS_CHANNEL_CAPACITY; ++slot) {
        micros_channel_t *channel = &runtime->channels[slot];
        size_t bytes = (size_t)channel->depth * channel->payload_bytes;
        if (channel->key) {
            const size_t alignment = _Alignof(micros_coord_channel_t);
            payload_storage += (bytes + alignment - 1) / alignment * alignment +
                               (runtime->coordination[slot] ? sizeof(micros_coord_channel_t) : 0);
        }
    }
    usage.channel_storage_bytes = sizeof(runtime->channels) + payload_storage;
    usage.kernel_metadata_bytes += payload_storage;
    usage.channel_payload_capacity = usage.channel_bytes;
    micros_platform_unlock(runtime->sync);
    return usage;
}
const char *micros_runtime_state_name(micros_service_state_t state)
{
    static const char *names[] = {"Unloaded", "Loaded",   "Initializing", "Starting",
                                  "Running",  "Stopping", "Stopped",      "Failed"};
    return (unsigned)state < sizeof(names) / sizeof(names[0]) ? names[state] : "Invalid";
}

micros_result_t micros_runtime_channel_status(micros_runtime_t *runtime, uint32_t slot,
                                               micros_channel_status_t *status)
{
    if (!runtime || !status || slot >= MICROS_CHANNEL_CAPACITY) return MICROS_ERROR_INVALID_ARGUMENT;
    micros_platform_lock(runtime->sync);
    micros_channel_t *channel = &runtime->channels[slot];
    *status = (micros_channel_status_t){.key=channel->key, .policy=channel->policy,
        .depth=channel->depth, .payload_bytes=channel->payload_bytes, .published=channel->sequence,
        .missed=runtime->channel_missed[slot],
        .age_us=channel->sequence ? micros_platform_now_us()-runtime->channel_last_us[slot] : 0};
    /* Reader progress does not reclaim ring storage. Ignore stale slots after recreation. */
    uint32_t retained = channel->sequence < channel->depth ? (uint32_t)channel->sequence : channel->depth;
    for (uint32_t index = 0; index < retained; ++index)
        status->retained_bytes += channel->lengths[index];
    for (size_t index=0; index<MICROS_RUNTIME_HANDLE_CAPACITY; ++index) {
        resource_slot_t *resource=&runtime->resources[index];
        if ((resource->kind != RESOURCE_PUBLISHER && resource->kind != RESOURCE_SUBSCRIBER) ||
            !resource->owner || resource->channel_slot != slot ||
            resource->channel_generation != channel->generation) continue;
        if (resource->kind == RESOURCE_PUBLISHER) ++status->publishers;
        if (resource->kind == RESOURCE_SUBSCRIBER) {
            ++status->subscribers;
            uint64_t pending=channel->sequence >= resource->next_sequence ?
                channel->sequence-resource->next_sequence+1 : 0;
            if (pending > channel->depth) pending=channel->depth;
            if (pending > status->backlog) status->backlog=(uint32_t)pending;
        }
    }
    micros_platform_unlock(runtime->sync);
    return status->key ? MICROS_OK : MICROS_ERROR_INVALID_ARGUMENT;
}

/* Privileged host transport adapter. Reuses an already-open service port under
 * the runtime lock; never creates grants, runs hooks or touches service memory.
 * The bridge service deliberately leaves these ports to its host transport. */
static micros_result_t console_port(micros_runtime_t *runtime, micros_instance_t instance,
    uint32_t key, const uint8_t *input, uint32_t input_bytes, uint8_t *output,
    uint32_t capacity, uint32_t *bytes, micros_message_info_t *info, int write)
{
    if (!runtime || !key || key > 32 || (write ? (!input && input_bytes) : (!output || !bytes || !info)))
        return MICROS_ERROR_INVALID_ARGUMENT;
    micros_platform_lock(runtime->sync);
    service_slot_t *service = find_service(runtime, instance);
    micros_result_t result = MICROS_ERROR_UNSUPPORTED;
    if (runtime->usage.reboot_required) result = MICROS_ERROR_REBOOT_REQUIRED;
    else if (!service || service->state != MICROS_STATE_RUNNING || service->stop_requested)
        result = MICROS_ERROR_STATE;
    else for (unsigned i=0; i<MICROS_RUNTIME_HANDLE_CAPACITY; ++i) {
        resource_slot_t *port = &runtime->resources[i];
        if (port->owner != instance || port->kind != (write ? RESOURCE_PUBLISHER : RESOURCE_SUBSCRIBER)) continue;
        micros_channel_t *channel = resource_channel(runtime, port);
        if (!channel || channel->key != key || (runtime->coordination[port->channel_slot] && runtime->coordination[port->channel_slot]->kind)) continue;
        if (write) {
            result = micros_channel_publish(channel, input, input_bytes);
            if (!result) { runtime->channel_last_us[port->channel_slot] = micros_platform_now_us(); micros_platform_notify(runtime->sync); }
        } else {
            result = micros_channel_read(channel, &port->next_sequence, output, capacity, bytes, info);
            if (!result || result == MICROS_ERROR_MESSAGES_MISSED)
                runtime->channel_missed[port->channel_slot] += info->messages_missed;
        }
        break;
    }
    micros_platform_unlock(runtime->sync);
    return result;
}
micros_result_t micros_runtime_console_write(micros_runtime_t *r, micros_instance_t instance,
    uint32_t key, const uint8_t *payload, uint32_t bytes)
{ return console_port(r,instance,key,payload,bytes,NULL,0,NULL,NULL,1); }
micros_result_t micros_runtime_console_read(micros_runtime_t *r, micros_instance_t instance,
    uint32_t key, uint8_t *payload, uint32_t capacity, uint32_t *bytes, micros_message_info_t *info)
{ return console_port(r,instance,key,NULL,0,payload,capacity,bytes,info,0); }

micros_result_t micros_runtime_wait_running(micros_runtime_t *runtime, micros_instance_t instance,
                                             uint64_t timeout_us)
{
    if (!runtime) return MICROS_ERROR_INVALID_ARGUMENT;
    micros_platform_lock(runtime->sync);
    uint64_t deadline = micros_platform_now_us() + timeout_us;
    micros_result_t result = MICROS_ERROR_STATE;
    for (;;) {
        service_slot_t *service = find_service(runtime, instance);
        if (!service) break;
        if (runtime->usage.reboot_required) { result = MICROS_ERROR_REBOOT_REQUIRED; break; }
        if (service->state == MICROS_STATE_RUNNING) { result = MICROS_OK; break; }
        if (service->state == MICROS_STATE_FAILED || service->finished) {
            result = service->result ? service->result : MICROS_ERROR_STATE;
            break;
        }
        if (micros_platform_now_us() >= deadline) break;
        micros_platform_wait(runtime->sync, deadline);
    }
    micros_platform_unlock(runtime->sync);
    return result;
}
