#ifndef MICROS_MEMORY_H
#define MICROS_MEMORY_H
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Includes the fixed pool header and worst-case 16-byte alignment padding. */
static inline size_t micros_memory_cost(size_t bytes) {
    return bytes > SIZE_MAX - 31 ? SIZE_MAX : ((bytes + 15) & ~(size_t)15) + 16;
}

/* Small targets back these allocations with distinct, fixed application and
 * management arenas. Exhaustion returns NULL; neither arena borrows heap RAM. */
#ifdef MICROS_STATIC_MEMORY
void *micros_memory_allocate(size_t bytes);
void micros_memory_free(void *pointer);
void *micros_management_allocate(size_t bytes);
void micros_management_free(void *pointer);
#else
static inline void *micros_memory_allocate(size_t bytes) { return calloc(1, bytes); }
static inline void micros_memory_free(void *pointer) { free(pointer); }
static inline void *micros_management_allocate(size_t bytes) { return malloc(bytes); }
static inline void micros_management_free(void *pointer) { free(pointer); }
#endif
#ifdef __cplusplus
}
#endif
#endif
