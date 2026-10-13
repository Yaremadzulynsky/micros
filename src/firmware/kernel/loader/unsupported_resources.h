#ifndef MICROS_UNSUPPORTED_RESOURCES_H
#define MICROS_UNSUPPORTED_RESOURCES_H
#include <micros/service.h>
/* M1 harnesses implement the current API table but have no resource manager.
 * Explicit stubs make capability absence observable instead of exposing NULL. */
static inline micros_result_t micros_unsupported_timer_open(micros_context_t *context,
                                                            uint64_t delay_us, uint64_t period_us,
                                                            micros_timer_callback_t callback,
                                                            void *user_data,
                                                            micros_handle_t *handle)
{
    (void)context;
    (void)delay_us;
    (void)period_us;
    (void)callback;
    (void)user_data;
    (void)handle;
    return MICROS_ERROR_UNSUPPORTED;
}
static inline micros_result_t micros_unsupported_resource_close(micros_context_t *context,
                                                                micros_handle_t handle)
{
    (void)context;
    (void)handle;
    return MICROS_ERROR_UNSUPPORTED;
}
static inline micros_result_t micros_unsupported_gpio_open(micros_context_t *context, uint32_t line,
                                                           micros_handle_t *handle)
{
    (void)context;
    (void)line;
    (void)handle;
    return MICROS_ERROR_UNSUPPORTED;
}
static inline micros_result_t micros_unsupported_gpio_read(micros_context_t *context,
                                                           micros_handle_t handle, uint32_t *level)
{
    (void)context;
    (void)handle;
    (void)level;
    return MICROS_ERROR_UNSUPPORTED;
}
static inline micros_result_t micros_unsupported_gpio_write(micros_context_t *context,
                                                            micros_handle_t handle, uint32_t level)
{
    (void)context;
    (void)handle;
    (void)level;
    return MICROS_ERROR_UNSUPPORTED;
}
static inline micros_result_t micros_unsupported_ipc_open(micros_context_t *context,
    uint32_t key, uint32_t access, micros_handle_t *handle)
{ (void)context; (void)key; (void)access; (void)handle; return MICROS_ERROR_UNSUPPORTED; }
static inline micros_result_t micros_unsupported_ipc_publish(micros_context_t *context,
    micros_handle_t handle, const uint8_t *bytes, uint32_t size)
{ (void)context; (void)handle; (void)bytes; (void)size; return MICROS_ERROR_UNSUPPORTED; }
static inline micros_result_t micros_unsupported_ipc_read(micros_context_t *context,
    micros_handle_t handle, uint8_t *bytes, uint32_t capacity, uint32_t *size, micros_message_info_t *info)
{ (void)context; (void)handle; (void)bytes; (void)capacity; (void)size; (void)info; return MICROS_ERROR_UNSUPPORTED; }
#endif
