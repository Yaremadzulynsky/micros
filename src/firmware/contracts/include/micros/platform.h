#ifndef MICROS_PLATFORM_H
#define MICROS_PLATFORM_H
#include <micros/service.h>
#include <micros/deployment.h>
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

/** @brief Platform-owned mutex and condition variable used for runtime coordination. */
typedef struct micros_platform_sync micros_platform_sync_t;
/** @brief Joinable platform task; joining releases its platform metadata. */
typedef struct micros_platform_task micros_platform_task_t;
/** @brief Loaded native image whose descriptor remains valid until close. */
typedef struct micros_platform_image micros_platform_image_t;

/** @brief BSP-owned digital lines; the kernel validates handles before access. */
typedef struct micros_platform_gpio micros_platform_gpio_t;
micros_platform_gpio_t *micros_platform_gpio_create(uint32_t line_count);
void micros_platform_gpio_destroy(micros_platform_gpio_t *gpio);
micros_result_t micros_platform_gpio_read(micros_platform_gpio_t *gpio, uint32_t line,
                                          uint32_t *level);
micros_result_t micros_platform_gpio_write(micros_platform_gpio_t *gpio, uint32_t line,
                                           uint32_t level);
micros_result_t micros_platform_gpio_read_analog(micros_platform_gpio_t *, uint32_t line,
                                                uint32_t *raw);
/** Restore a released analog pin's input mode; called under the runtime lock. */
void micros_platform_gpio_release(micros_platform_gpio_t *, uint32_t line);

micros_platform_sync_t *micros_platform_sync_create(void);
void micros_platform_sync_destroy(micros_platform_sync_t *sync);
void micros_platform_lock(micros_platform_sync_t *sync);
void micros_platform_unlock(micros_platform_sync_t *sync);
void micros_platform_notify(micros_platform_sync_t *sync);
/* Caller holds the lock; wait releases it and reacquires it before return. */
void micros_platform_wait(micros_platform_sync_t *sync, uint64_t deadline_us);
uint64_t micros_platform_now_us(void);
size_t micros_platform_stack_bytes(size_t requested_bytes);
size_t micros_platform_metadata_bytes(uint32_t gpio_lines);
size_t micros_platform_task_metadata_bytes(void);
/* Static targets reserve service stacks during admission, before any hook runs. */
micros_platform_task_t *micros_platform_task_create_with_stack(void *(*entry)(void *),
    void *argument, size_t bytes, void *stack);
micros_platform_task_t *micros_platform_task_create(void *(*entry)(void *), void *argument,
                                                    size_t stack_bytes);
/** Create the independent deadline supervisor at the platform's supervisory priority. */
micros_platform_task_t *micros_platform_supervisor_create(void *(*entry)(void *), void *argument,
                                                          size_t stack_bytes);
/** Arena allocation must satisfy native alignment and the platform's internal-memory rules. */
void *micros_platform_arena_allocate(size_t alignment, size_t bytes, uint32_t placement);
/** Release an arena with the matching target allocator; every target implements this. */
void micros_platform_arena_free(void *arena);
/** Return remaining stack bytes where measured; zero means unavailable on the host. */
size_t micros_platform_stack_free(micros_platform_task_t *task);
void micros_platform_task_join(micros_platform_task_t *task);
/** Route service diagnostics away from the management protocol before starting tasks. */
void micros_platform_debug_to_stderr(void);
micros_result_t micros_platform_debug(const uint8_t *message, uint32_t message_bytes);
micros_result_t micros_platform_image_open(const char *path, micros_platform_image_t **image,
                                           const micros_service_descriptor_t **descriptor,
                                           size_t *payload_bytes);
void micros_platform_image_close(micros_platform_image_t *image);
void micros_controller_initialize(uint64_t *boot_identity);
void micros_controller_reset(void);
/** Optional physical USB loader entry; call only when USB_BOOTLOADER is supported. */
void micros_controller_bootloader(void);
unsigned micros_controller_reset_reason(void);
size_t micros_controller_heap_free(void);
int micros_controller_gpio_level(int pin);
int micros_controller_recovery_pressed(int pin);
const uint8_t *micros_controller_base_hash(void);
void micros_controller_identity(uint8_t identity[6]);
void *micros_controller_transfer_allocate(size_t bytes);
void micros_controller_yield(void);
/** @brief Validate/apply deployment pin bindings only while the runtime is stopped. */
int micros_board_validate_gpio(const micros_device_graph_t *graph);
int micros_board_apply_gpio(const micros_device_graph_t *graph);
int micros_board_recovery_pin(void);
unsigned micros_board_gpio_bindings(const micros_graph_gpio_t **bindings);
int micros_board_validate_image(const char *path, unsigned expected_slot);
int micros_board_validate_bytes(const void *bytes, size_t size, unsigned expected_slot);
#ifdef __cplusplus
}
#endif
#endif
