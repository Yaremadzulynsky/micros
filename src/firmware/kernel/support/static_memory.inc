/* Included by a small-board backend after its RTOS and panic declarations. */
#include "fixed_pool.h"
#include <micros/memory.h>
static _Alignas(16) unsigned char application_memory[MICROS_APPLICATION_POOL_BYTES];
static _Alignas(16) unsigned char management_memory[MICROS_MANAGEMENT_POOL_BYTES];
void *micros_memory_allocate(size_t bytes) {
    taskENTER_CRITICAL();
    void *pointer = micros_pool_take(application_memory, sizeof(application_memory), bytes);
    taskEXIT_CRITICAL();
    return pointer;
}
void micros_memory_free(void *pointer) {
    taskENTER_CRITICAL();
    int valid = micros_pool_release(application_memory, sizeof(application_memory), pointer);
    taskEXIT_CRITICAL();
    if (!valid) MICROS_MEMORY_PANIC();
}
void *micros_management_allocate(size_t bytes) {
    taskENTER_CRITICAL();
    void *pointer = micros_pool_take(management_memory, sizeof(management_memory), bytes);
    taskEXIT_CRITICAL();
    return pointer;
}
void micros_management_free(void *pointer) {
    taskENTER_CRITICAL();
    int valid = micros_pool_release(management_memory, sizeof(management_memory), pointer);
    taskEXIT_CRITICAL();
    if (!valid) MICROS_MEMORY_PANIC();
}
