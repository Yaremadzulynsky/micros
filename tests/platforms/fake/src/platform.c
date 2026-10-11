/* Link-only port fixture: deliberately no OS, SDK, hardware or native execution.
 * This is not a working platform and must never be shipped. */
#include <micros/platform.h>
#include <micros/capabilities.h>
#include <stdlib.h>
micros_platform_gpio_t *micros_platform_gpio_create(uint32_t n) { return NULL; }
void micros_platform_gpio_destroy(micros_platform_gpio_t *g) {}
micros_result_t micros_platform_gpio_read(micros_platform_gpio_t *g,uint32_t n,uint32_t *v) { return MICROS_ERROR_UNSUPPORTED; }
micros_result_t micros_platform_gpio_write(micros_platform_gpio_t *g,uint32_t n,uint32_t v) { return MICROS_ERROR_UNSUPPORTED; }
micros_result_t micros_platform_gpio_read_analog(micros_platform_gpio_t *g,uint32_t n,uint32_t *v) { return MICROS_ERROR_UNSUPPORTED; }
void micros_platform_gpio_release(micros_platform_gpio_t *g,uint32_t n) {}
micros_platform_sync_t *micros_platform_sync_create(void) { return NULL; }
void micros_platform_sync_destroy(micros_platform_sync_t *s) {}
void micros_platform_lock(micros_platform_sync_t *s) {}
void micros_platform_unlock(micros_platform_sync_t *s) {}
void micros_platform_notify(micros_platform_sync_t *s) {}
void micros_platform_wait(micros_platform_sync_t *s,uint64_t d) {}
uint64_t micros_platform_now_us(void) { return 0; }
size_t micros_platform_stack_bytes(size_t n) { return n; }
size_t micros_platform_metadata_bytes(uint32_t n) { return 0; }
size_t micros_platform_task_metadata_bytes(void) { return 0; }
micros_platform_task_t *micros_platform_task_create(void *(*e)(void *),void *a,size_t n) { return NULL; }
micros_platform_task_t *micros_platform_supervisor_create(void *(*e)(void *),void *a,size_t n) { return NULL; }
void *micros_platform_arena_allocate(size_t a,size_t n,uint32_t p) { return NULL; }
void micros_platform_arena_free(void *a) {}
size_t micros_platform_stack_free(micros_platform_task_t *t) { return 0; }
void micros_platform_task_join(micros_platform_task_t *t) {}
void micros_platform_debug_to_stderr(void) {}
micros_result_t micros_platform_debug(const uint8_t *p,uint32_t n) { return MICROS_ERROR_UNSUPPORTED; }
micros_result_t micros_platform_image_open(const char *p,micros_platform_image_t **i,const micros_service_descriptor_t **d,size_t *n) { return MICROS_ERROR_UNSUPPORTED; }
void micros_platform_image_close(micros_platform_image_t *i) {}
#include <micros/platform.h>
#include <micros/storage.h>
#include <micros/transport.h>
#include <micros/network.h>
#include <micros/update.h>
#include <micros/telemetry.h>
void micros_controller_initialize(uint64_t *boot) {}
void micros_controller_reset(void) {}
unsigned micros_controller_reset_reason(void) { return 0; }
size_t micros_controller_heap_free(void) { return 0; }
int micros_controller_gpio_level(int pin) { return 0; }
int micros_controller_recovery_pressed(int pin) { return 0; }
const uint8_t *micros_controller_base_hash(void) { static uint8_t hash[32]; return hash; }
void micros_controller_identity(uint8_t identity[6]) {}
void *micros_controller_transfer_allocate(size_t bytes) { return NULL; }
#ifndef OMIT_REQUIRED_OPERATION
void micros_controller_yield(void) {}
#endif
int micros_board_validate_gpio(const micros_device_graph_t *graph) { return 0; }
int micros_board_apply_gpio(const micros_device_graph_t *graph) { return 0; }
int micros_board_recovery_pin(void) { return -1; }
unsigned micros_board_gpio_bindings(const micros_graph_gpio_t **bindings) { return 0; }
int micros_board_validate_image(const char *path,unsigned slot) { return 0; }
int micros_board_validate_bytes(const void *data,size_t size,unsigned slot) { return 0; }

void micros_controller_bootloader(void) {}
