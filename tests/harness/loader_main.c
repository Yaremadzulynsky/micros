#define _DARWIN_C_SOURCE
#define _POSIX_C_SOURCE 200809L /* Request POSIX.1-2008 declarations. */
#include "image.h"
#include "m1_limits.h"
#include "unsupported_resources.h"
#include <dlfcn.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

/* Host-only stack floor: leave room for libc/pthread call frames during the
 * harness; this is chosen policy, not the platform minimum or an MCU budget. */
#include "host_stack.h"
/* Distinct from ordinary exit failure (1): the thread may still be executing. */
#define HOST_EXIT_SERVICE_TIMEOUT 2

/**
 * @brief Host-owned instance state passed opaquely through service API calls.
 *
 * Lives for one load/run cycle and records accepted diagnostic write attempts
 * for the harness report. The service accesses it only through API callbacks.
 */
struct micros_context {
    /** Write attempts that passed argument and capacity checks. */
    unsigned diagnostic_write_count;
};
static micros_result_t debug_write(micros_context_t *context, const uint8_t *message,
                                   uint32_t message_bytes)
{
    if (message_bytes > MICROS_DEBUG_MAX_BYTES)
        return MICROS_ERROR_CAPACITY;
    if (!message && message_bytes)
        return MICROS_ERROR_INVALID_ARGUMENT;
    context->diagnostic_write_count++;
    return fwrite(message, 1, message_bytes, stdout) == message_bytes ? MICROS_OK
                                                                      : MICROS_ERROR_SERVICE;
}
static uint64_t monotonic_us(micros_context_t *context)
{
    (void)context;
    struct timespec timestamp;
    clock_gettime(CLOCK_MONOTONIC, &timestamp);
    return (uint64_t)timestamp.tv_sec * MICROS_US_PER_SECOND +
           (uint64_t)timestamp.tv_nsec / MICROS_NS_PER_US;
}
/**
 * @brief One host service run shared by the worker thread and its supervisor.
 *
 * Bundles the loaded descriptor and hook resources with deadline/completion
 * coordination. The supervisor keeps it alive until the worker is joined;
 * deadline and completion updates are published under lock via state_changed.
 */
typedef struct {
    /** Service-owned metadata and hooks, valid until the library is unloaded. */
    const micros_service_descriptor_t *descriptor;
    /** Loader-owned resources passed to each hook. */
    micros_service_args_t service_args;
    /** Mutex protecting publication of deadline, completion, and result. */
    pthread_mutex_t lock;
    /** Wakes the supervisor when the deadline changes or execution finishes. */
    pthread_cond_t state_changed;
    /** Nonzero once the worker has finished all hooks, including stop. */
    int has_finished;
    /** Monotonic deadline in microseconds for the current execution phase. */
    uint64_t deadline_us;
    /** Final lifecycle result, published with has_finished. */
    micros_result_t result;
} service_execution_t;
/* Publish the active hook deadline so the supervisor can detect a stuck task. */
static micros_result_t invoke(service_execution_t *execution, micros_service_hook_t hook,
                              uint64_t hook_budget_us)
{
    pthread_mutex_lock(&execution->lock);
    execution->deadline_us = monotonic_us(NULL) + hook_budget_us;
    pthread_cond_signal(&execution->state_changed);
    pthread_mutex_unlock(&execution->lock);
    micros_result_t result = hook(&execution->service_args);
    if (monotonic_us(NULL) > execution->deadline_us)
        result = MICROS_ERROR_SERVICE;
    return result;
}
/* All hooks run serially on this thread; the supervisor joins before unload. */
static void *execute(void *thread_argument)
{
    service_execution_t *execution = thread_argument;
    micros_result_t hook_result =
        invoke(execution, execution->descriptor->init,
               (uint64_t)MICROS_M1_LIFECYCLE_TIMEOUT_MS * MICROS_US_PER_MS);
    if (!hook_result)
        hook_result = invoke(execution, execution->descriptor->start,
                             (uint64_t)MICROS_M1_LIFECYCLE_TIMEOUT_MS * MICROS_US_PER_MS);
    for (int step_index = 0; step_index < MICROS_M1_STEP_COUNT && !hook_result; ++step_index) {
        hook_result = invoke(execution, execution->descriptor->step,
                             (uint64_t)MICROS_M1_STEP_TIMEOUT_MS * MICROS_US_PER_MS);
        /* The nominal yield is not part of the hook's execution budget. */
        pthread_mutex_lock(&execution->lock);
        execution->deadline_us =
            monotonic_us(NULL) + (uint64_t)MICROS_M1_LIFECYCLE_TIMEOUT_MS * MICROS_US_PER_MS;
        pthread_cond_signal(&execution->state_changed);
        pthread_mutex_unlock(&execution->lock);
        struct timespec step_delay = {0, MICROS_M1_STEP_DELAY_MS * MICROS_US_PER_MS *
                                             MICROS_NS_PER_US};
        nanosleep(&step_delay, NULL);
    }
    micros_result_t stop_result =
        invoke(execution, execution->descriptor->stop,
               (uint64_t)MICROS_M1_LIFECYCLE_TIMEOUT_MS * MICROS_US_PER_MS);
    pthread_mutex_lock(&execution->lock);
    execution->result = hook_result ? hook_result : stop_result;
    execution->has_finished = 1;
    pthread_cond_signal(&execution->state_changed);
    pthread_mutex_unlock(&execution->lock);
    return NULL;
}
static int run(const uint8_t *image_bytes, size_t image_size, unsigned cycle_number)
{
    micros_image_t image;
    const char *error = micros_image_validate(image_bytes, image_size, MICROS_BUILD_TARGET, &image);
    if (error) {
        fprintf(stderr, "REJECT %s\n", error);
        return 1;
    }
    char temporary_library_path[] = "/tmp/micros-service-XXXXXX";
    int temporary_descriptor = mkstemp(temporary_library_path);
    if (temporary_descriptor < 0) {
        perror("mkstemp");
        return 1;
    }
    FILE *image_file = fdopen(temporary_descriptor, "wb");
    if (!image_file) {
        close(temporary_descriptor);
        unlink(temporary_library_path);
        return 1;
    }
    size_t written_bytes =
        fwrite(image_bytes + MICROS_IMAGE_HEADER_BYTES, 1, image.code_bytes, image_file);
    int close_result = fclose(image_file);
    if (written_bytes != image.code_bytes || close_result) {
        unlink(temporary_library_path);
        return 1;
    }
    void *service_library = dlopen(temporary_library_path, RTLD_NOW | RTLD_LOCAL);
    if (!service_library) {
        fprintf(stderr, "REJECT native loader: %s\n", dlerror());
        unlink(temporary_library_path);
        return 1;
    }
    unlink(temporary_library_path); /* Mapping stays valid; fatal process recovery must not leak
                                       files. */
    void *query_symbol = dlsym(service_library, "micros_service_query");
    const micros_service_descriptor_t *(*query_descriptor)(void) = NULL;
    _Static_assert(sizeof(query_descriptor) == sizeof(query_symbol), "host function pointer");
    memcpy(&query_descriptor, &query_symbol, sizeof(query_descriptor));
    const micros_service_descriptor_t *descriptor = query_descriptor ? query_descriptor() : NULL;
    error = micros_descriptor_validate(descriptor, MICROS_BUILD_TARGET);
    if (error) {
        fprintf(stderr, "REJECT %s\n", error);
        dlclose(service_library);
        unlink(temporary_library_path);
        return 1;
    }
    void *arena = NULL;
    size_t arena_alignment =
        descriptor->arena_alignment < sizeof(void *) ? sizeof(void *) : descriptor->arena_alignment;
    if (posix_memalign(&arena, arena_alignment,
                       descriptor->arena_bytes ? descriptor->arena_bytes : 1)) {
        dlclose(service_library);
        unlink(temporary_library_path);
        return 1;
    }
    memset(arena, 0, descriptor->arena_bytes);
    micros_context_t context = {0};
    const micros_api_t api = {.struct_bytes = sizeof(micros_api_t),
                              .abi_major = MICROS_ABI_MAJOR,
                              .abi_revision = MICROS_ABI_REVISION,
                              .debug_write = debug_write,
                              .monotonic_us = monotonic_us,
                              .timer_open = micros_unsupported_timer_open,
                              .timer_close = micros_unsupported_resource_close,
                              .gpio_open = micros_unsupported_gpio_open,
                              .gpio_read = micros_unsupported_gpio_read,
                              .gpio_write = micros_unsupported_gpio_write,
                              .gpio_close = micros_unsupported_resource_close,
                              ._ipc = NULL};
    service_execution_t execution = {.descriptor = descriptor,
                                     .service_args = {sizeof(execution.service_args),
                                                      descriptor->arena_bytes, &context, &api,
                                                      arena, NULL, 0},
                                     .lock = PTHREAD_MUTEX_INITIALIZER,
                                     .state_changed = PTHREAD_COND_INITIALIZER};
#ifndef __APPLE__
    pthread_cond_destroy(&execution.state_changed);
    pthread_condattr_t condition_attributes;
    pthread_condattr_init(&condition_attributes);
    pthread_condattr_setclock(&condition_attributes, CLOCK_MONOTONIC);
    pthread_cond_init(&execution.state_changed, &condition_attributes);
    pthread_condattr_destroy(&condition_attributes);
#endif
    pthread_attr_t thread_attributes;
    pthread_attr_init(&thread_attributes);
    size_t host_stack_bytes = descriptor->stack_bytes;
    if (host_stack_bytes < micros_host_stack_floor())
        host_stack_bytes =
            micros_host_stack_floor(); /* Host adapter minimum; distinct from MCU budget. */
    if (pthread_attr_setstacksize(&thread_attributes, host_stack_bytes)) {
        fprintf(stderr, "stack configuration failed\n");
        exit(1);
    }
    execution.deadline_us =
        monotonic_us(NULL) + (uint64_t)MICROS_M1_LIFECYCLE_TIMEOUT_MS * MICROS_US_PER_MS;
    pthread_t service_thread;
    if (pthread_create(&service_thread, &thread_attributes, execute, &execution)) {
        fprintf(stderr, "task creation failed\n");
        exit(1);
    }
    pthread_attr_destroy(&thread_attributes);
    pthread_mutex_lock(&execution.lock);
    while (!execution.has_finished) {
        uint64_t current_time_us = monotonic_us(NULL);
        if (current_time_us >= execution.deadline_us) {
            fprintf(stderr, "FATAL service deadline; process recovery required\n");
            fflush(NULL);
            _Exit(HOST_EXIT_SERVICE_TIMEOUT);
        }
        uint64_t remaining_us = execution.deadline_us - current_time_us;
        struct timespec wait_interval = {(time_t)(remaining_us / MICROS_US_PER_SECOND),
                                         (long)(remaining_us % MICROS_US_PER_SECOND) *
                                             MICROS_NS_PER_US};
        /* macOS relative condition waits avoid wall-clock adjustments. */
#ifdef __APPLE__
        (void)pthread_cond_timedwait_relative_np(&execution.state_changed, &execution.lock,
                                                 &wait_interval);
#else
        (void)wait_interval;
        struct timespec deadline = {(time_t)(execution.deadline_us / MICROS_US_PER_SECOND),
                                    (long)(execution.deadline_us % MICROS_US_PER_SECOND) *
                                        MICROS_NS_PER_US};
        pthread_cond_timedwait(&execution.state_changed, &execution.lock, &deadline);
#endif
    }
    pthread_mutex_unlock(&execution.lock);
    pthread_join(service_thread, NULL);
    printf("CYCLE %u result=%d image=%u arena=%u stack_requested=%u stack_host=%zu writes=%u\n",
           cycle_number, execution.result, image.code_bytes, descriptor->arena_bytes,
           descriptor->stack_bytes, host_stack_bytes, context.diagnostic_write_count);
    int result = execution.result != MICROS_OK;
    pthread_cond_destroy(&execution.state_changed);
    pthread_mutex_destroy(&execution.lock);
    free(arena);
    dlclose(service_library);
    unlink(temporary_library_path);
    return result;
}
int main(int argc, char **argv)
{
    /* Executable name plus exactly one image path. */
    if (argc != 2) {
        fprintf(stderr, "usage: micros-host SERVICE.mimg\n");
        return 1;
    }
    FILE *image_file = fopen(argv[1], "rb");
    if (!image_file) {
        perror("open");
        return 1;
    }
    if (fseek(image_file, 0, SEEK_END))
        return 1;
    long image_size = ftell(image_file);
    if (image_size < 0 || image_size > MICROS_IMAGE_LIMIT) {
        fprintf(stderr, "REJECT image length\n");
        fclose(image_file);
        return 1;
    }
    rewind(image_file);
    uint8_t *image_bytes = malloc(image_size ? (size_t)image_size : 1);
    if (!image_bytes)
        return 1;
    if (fread(image_bytes, 1, (size_t)image_size, image_file) != (size_t)image_size) {
        fclose(image_file);
        free(image_bytes);
        return 1;
    }
    fclose(image_file);
    /* Two numbered cycles exercise the first load and a clean reload. */
    int result = run(image_bytes, (size_t)image_size, 1);
    if (!result)
        result = run(image_bytes, (size_t)image_size, 2);
    free(image_bytes);
    return result;
}
