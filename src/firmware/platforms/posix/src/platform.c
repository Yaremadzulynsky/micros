#include <micros/capabilities.h>
MICROS_REQUIRE_CAPABILITY(NATIVE_SERVICES);
#define _DARWIN_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#include "image.h"
#include <dlfcn.h>
#include <micros/platform.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

/* Unit conversions reflect POSIX timespec units; the host stack floor leaves
 * room for pthread/libc frames beyond the service's MCU-oriented request. */
#define US_PER_SECOND UINT64_C(1000000)
#define NS_PER_US 1000u
#include "support/host_stack.h"

/** @brief POSIX synchronization backing the runtime's single coordination lock. */
struct micros_platform_sync {
    pthread_mutex_t mutex;
    pthread_cond_t changed;
};
/** @brief Joinable pthread metadata; the OS owns the actual stack allocation. */
struct micros_platform_task {
    pthread_t thread;
};
/** @brief dlopen reference that keeps native hooks and globals mapped. */
struct micros_platform_image {
    void *library;
};

/** @brief Host digital line levels; accessed only under the owning runtime's lock. */
struct micros_platform_gpio {
    uint32_t reserved;
    uint32_t levels[];
};
size_t micros_platform_metadata_bytes(uint32_t gpio_lines)
{
    return sizeof(micros_platform_sync_t) + sizeof(micros_platform_gpio_t) +
           gpio_lines * sizeof(uint32_t);
}
size_t micros_platform_task_metadata_bytes(void)
{
    return sizeof(micros_platform_task_t);
}
micros_platform_gpio_t *micros_platform_gpio_create(uint32_t line_count)
{
    return calloc(1, sizeof(micros_platform_gpio_t) + line_count * sizeof(uint32_t));
}
void micros_platform_gpio_destroy(micros_platform_gpio_t *gpio)
{
    free(gpio);
}
micros_result_t micros_platform_gpio_read(micros_platform_gpio_t *gpio, uint32_t line,
                                          uint32_t *level)
{
    *level = gpio->levels[line];
    return MICROS_OK;
}
micros_result_t micros_platform_gpio_write(micros_platform_gpio_t *gpio, uint32_t line,
                                           uint32_t level)
{
    gpio->levels[line] = level;
    return MICROS_OK;
}

micros_platform_sync_t *micros_platform_sync_create(void)
{
    micros_platform_sync_t *sync = calloc(1, sizeof(*sync));
    if (!sync)
        return NULL;
    if (pthread_mutex_init(&sync->mutex, NULL)) {
        free(sync);
        return NULL;
    }
    pthread_condattr_t attributes;
    pthread_condattr_init(&attributes);
#ifndef __APPLE__
    pthread_condattr_setclock(&attributes, CLOCK_MONOTONIC);
#endif
    int condition_result = pthread_cond_init(&sync->changed, &attributes);
    pthread_condattr_destroy(&attributes);
    if (condition_result) {
        pthread_mutex_destroy(&sync->mutex);
        free(sync);
        return NULL;
    }
    return sync;
}
void micros_platform_sync_destroy(micros_platform_sync_t *sync)
{
    pthread_cond_destroy(&sync->changed);
    pthread_mutex_destroy(&sync->mutex);
    free(sync);
}
void micros_platform_lock(micros_platform_sync_t *sync)
{
    pthread_mutex_lock(&sync->mutex);
}
void micros_platform_unlock(micros_platform_sync_t *sync)
{
    pthread_mutex_unlock(&sync->mutex);
}
void micros_platform_notify(micros_platform_sync_t *sync)
{
    pthread_cond_broadcast(&sync->changed);
}
uint64_t micros_platform_now_us(void)
{
    struct timespec timestamp;
    clock_gettime(CLOCK_MONOTONIC, &timestamp);
    return (uint64_t)timestamp.tv_sec * US_PER_SECOND + (uint64_t)timestamp.tv_nsec / NS_PER_US;
}
void micros_platform_wait(micros_platform_sync_t *sync, uint64_t deadline_us)
{
    uint64_t now_us = micros_platform_now_us();
    if (deadline_us <= now_us)
        return;
    uint64_t remaining_us = deadline_us - now_us;
    struct timespec interval = {(time_t)(remaining_us / US_PER_SECOND),
                                (long)(remaining_us % US_PER_SECOND) * NS_PER_US};
#ifdef __APPLE__
    pthread_cond_timedwait_relative_np(&sync->changed, &sync->mutex, &interval);
#else
    (void)interval;
    struct timespec deadline = {(time_t)(deadline_us / US_PER_SECOND),
                                (long)(deadline_us % US_PER_SECOND) * NS_PER_US};
    pthread_cond_timedwait(&sync->changed, &sync->mutex, &deadline);
#endif
}
size_t micros_platform_stack_bytes(size_t requested_bytes)
{
    size_t stack_bytes =
        requested_bytes < micros_host_stack_floor() ? micros_host_stack_floor() : requested_bytes;
    size_t page_bytes = (size_t)sysconf(_SC_PAGESIZE);
    return (stack_bytes + page_bytes - 1) / page_bytes * page_bytes;
}
micros_platform_task_t *micros_platform_task_create(void *(*entry)(void *), void *argument,
                                                    size_t stack_bytes)
{
    micros_platform_task_t *task = malloc(sizeof(*task));
    if (!task)
        return NULL;
    pthread_attr_t attributes;
    if (pthread_attr_init(&attributes)) {
        free(task);
        return NULL;
    }
    int error = pthread_attr_setstacksize(&attributes, stack_bytes);
    if (!error)
        error = pthread_create(&task->thread, &attributes, entry, argument);
    pthread_attr_destroy(&attributes);
    if (error) {
        free(task);
        return NULL;
    }
    return task;
}
micros_platform_task_t *micros_platform_supervisor_create(void *(*entry)(void *), void *argument,
                                                          size_t stack_bytes)
{
    return micros_platform_task_create(entry, argument, stack_bytes);
}
void *micros_platform_arena_allocate(size_t alignment, size_t bytes, uint32_t placement)
{
    if (placement != 0) return NULL;
    return aligned_alloc(alignment, bytes);
}
size_t micros_platform_stack_free(micros_platform_task_t *task)
{
    (void)task;
    return 0;
}
void micros_platform_task_join(micros_platform_task_t *task)
{
    pthread_join(task->thread, NULL);
    free(task);
}
static int debug_stderr; /* Set once by the host management entry before starting workers. */
void micros_platform_debug_to_stderr(void)
{
    debug_stderr = 1;
}
micros_result_t micros_platform_debug(const uint8_t *message, uint32_t message_bytes)
{
    return fwrite(message, 1, message_bytes, debug_stderr ? stderr : stdout) == message_bytes
               ? MICROS_OK
               : MICROS_ERROR_SERVICE;
}
micros_result_t micros_platform_image_open(const char *path, micros_platform_image_t **output,
                                           const micros_service_descriptor_t **descriptor,
                                           size_t *payload_bytes)
{
    FILE *image_file = fopen(path, "rb");
    if (!image_file)
        return MICROS_ERROR_INVALID_ARGUMENT;
    if (fseek(image_file, 0, SEEK_END)) {
        fclose(image_file);
        return MICROS_ERROR_SERVICE;
    }
    long image_length = ftell(image_file);
    if (image_length < 0 || (unsigned long)image_length > MICROS_IMAGE_LIMIT) {
        fclose(image_file);
        return MICROS_ERROR_CAPACITY;
    }
    rewind(image_file);
    uint8_t *bytes = malloc(image_length ? (size_t)image_length : 1);
    if (!bytes) {
        fclose(image_file);
        return MICROS_ERROR_CAPACITY;
    }
    size_t read_bytes = fread(bytes, 1, (size_t)image_length, image_file);
    fclose(image_file);
    micros_image_t layout;
    if (read_bytes != (size_t)image_length ||
        micros_image_validate(bytes, read_bytes, MICROS_BUILD_TARGET, &layout)) {
        free(bytes);
        return MICROS_ERROR_INVALID_ARGUMENT;
    }
    /* A unique file per load gives each service independent globals/BSS. */
    char library_path[] = "/tmp/micros-runtime-XXXXXX";
    int file_descriptor = mkstemp(library_path);
    if (file_descriptor < 0) {
        free(bytes);
        return MICROS_ERROR_SERVICE;
    }
    FILE *library_file = fdopen(file_descriptor, "wb");
    if (!library_file) {
        close(file_descriptor);
        unlink(library_path);
        free(bytes);
        return MICROS_ERROR_SERVICE;
    }
    size_t written_bytes =
        fwrite(bytes + MICROS_IMAGE_HEADER_BYTES, 1, layout.code_bytes, library_file);
    int close_error = fclose(library_file);
    free(bytes);
    if (written_bytes != layout.code_bytes || close_error) {
        unlink(library_path);
        return MICROS_ERROR_SERVICE;
    }
    void *library = dlopen(library_path, RTLD_NOW | RTLD_LOCAL);
    unlink(library_path);
    if (!library)
        return MICROS_ERROR_SERVICE;
    void *query_symbol = dlsym(library, "micros_service_query");
    const micros_service_descriptor_t *(*query)(void) = NULL;
    _Static_assert(sizeof(query) == sizeof(query_symbol), "host function pointer width");
    memcpy(&query, &query_symbol, sizeof(query));
    const micros_service_descriptor_t *service_descriptor = query ? query() : NULL;
    if (micros_descriptor_validate(service_descriptor, MICROS_BUILD_TARGET)) {
        dlclose(library);
        return MICROS_ERROR_INVALID_ARGUMENT;
    }
    micros_platform_image_t *image = malloc(sizeof(*image));
    if (!image) {
        dlclose(library);
        return MICROS_ERROR_CAPACITY;
    }
    image->library = library;
    *output = image;
    *descriptor = service_descriptor;
    *payload_bytes = layout.code_bytes;
    return MICROS_OK;
}
void micros_platform_image_close(micros_platform_image_t *image)
{
    dlclose(image->library);
    free(image);
}

void micros_platform_arena_free(void *arena) { free(arena); }

/* This target's service ABI has no analog implementation. Builds requiring
 * analog GPIO are rejected by the capability contract before linking. */
micros_result_t micros_platform_gpio_read_analog(micros_platform_gpio_t *gpio,
                                                uint32_t line, uint32_t *raw)
{ (void)gpio; (void)line; (void)raw; return MICROS_ERROR_UNSUPPORTED; }
void micros_platform_gpio_release(micros_platform_gpio_t *gpio, uint32_t line)
{ (void)gpio; (void)line; }

/* Controller mechanisms use the same contract as embedded targets. */
#include <micros/capabilities.h>
#include <micros/telemetry.h>
void micros_controller_initialize(uint64_t *identity) {
 micros_platform_debug_to_stderr();*identity=micros_platform_now_us() ^ (uint64_t)getpid();
}
void micros_controller_reset(void) { _exit(75); }
unsigned micros_controller_reset_reason(void) { return 0; }
size_t micros_controller_heap_free(void) { return 0; }
int micros_controller_gpio_level(int pin) { (void)pin;return 0; }
int micros_controller_recovery_pressed(int pin) { (void)pin;return 0; }
const uint8_t *micros_controller_base_hash(void) { static const uint8_t hash[32]={0};return hash; }
void micros_controller_identity(uint8_t identity[6]) {
 uint64_t value=(uint64_t)getpid();memcpy(identity,&value,6);
}
void *micros_controller_transfer_allocate(size_t bytes) { return malloc(bytes); }
void micros_controller_yield(void) { struct timespec delay={0,1000000};nanosleep(&delay,0); }
int micros_board_recovery_pin(void) { return -1; }
int micros_board_validate_gpio(const micros_device_graph_t *graph) {
 if (graph->gpio_count>4 || (graph->recovery_line!=UINT32_MAX && graph->recovery_line>=graph->gpio_count)) return 0;
 for (unsigned i=0;i<graph->gpio_count;++i) {
  if (graph->gpio[i].pin>=32 || graph->gpio[i].output>1) return 0;
  for (unsigned j=0;j<i;++j) if (graph->gpio[i].pin==graph->gpio[j].pin) return 0;
 }
 return 1;
}
int micros_board_apply_gpio(const micros_device_graph_t *graph) { return micros_board_validate_gpio(graph); }
unsigned micros_board_gpio_bindings(const micros_graph_gpio_t **bindings) { *bindings=NULL;return 0; }
int micros_board_validate_bytes(const void *bytes,size_t size,unsigned slot) {
 micros_image_t image;
 return slot>=4 || micros_image_validate(bytes,size,MICROS_BUILD_TARGET,&image) ? MICROS_ERROR_INVALID_ARGUMENT : MICROS_OK;
}
int micros_board_validate_image(const char *path,unsigned slot) {
 if (slot>=4) return MICROS_ERROR_INVALID_ARGUMENT;
 micros_platform_image_t *image=NULL;const micros_service_descriptor_t *descriptor;size_t bytes;
 int result=micros_platform_image_open(path,&image,&descriptor,&bytes);
 if (!result) micros_platform_image_close(image);
 return result;
}

void micros_controller_bootloader(void) {}

/* This backend owns task stack allocation; caller-owned stacks are unsupported. */
micros_platform_task_t *micros_platform_task_create_with_stack(void *(*entry)(void *),
    void *argument, size_t bytes, void *stack)
{
    (void)entry; (void)argument; (void)bytes; (void)stack;
    return NULL;
}
