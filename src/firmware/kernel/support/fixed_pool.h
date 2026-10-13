#ifndef MICROS_FIXED_POOL_H
#define MICROS_FIXED_POOL_H
#include <stddef.h>
#include <stdint.h>
#include <string.h>
/* A finite, caller-owned arena. No libc allocation and no fallback. Each block
 * starts on a 16-byte boundary; free neighbours coalesce immediately. Callers
 * serialize access. The header is deliberately independent of pointer width. */
typedef struct { uint32_t span, used; uint32_t reserved[2]; } micros_pool_block_t;
#define MICROS_POOL_ALIGNMENT 16u
static inline void *micros_pool_take(void *storage, size_t capacity, size_t bytes)
{
    if (!bytes || capacity < 32 || capacity > UINT32_MAX || capacity % 16 ||
        bytes > capacity - 16) return NULL;
    uint8_t *base = storage;
    micros_pool_block_t *first = (void *)base;
    if (!first->span) first->span = (uint32_t)capacity;
    size_t needed = ((bytes + 15) & ~(size_t)15) + 16;
    for (size_t offset = 0; offset < capacity;) {
        micros_pool_block_t *block = (void *)(base + offset);
        if (!block->used && block->span >= needed) {
            if (block->span >= needed + 32) {
                micros_pool_block_t *tail = (void *)(base + offset + needed);
                *tail = (micros_pool_block_t){.span = block->span - (uint32_t)needed};
                block->span = (uint32_t)needed;
            }
            block->used = 1;
            void *result = block + 1;
            memset(result, 0, block->span - 16);
            return result;
        }
        offset += block->span;
    }
    return NULL;
}
static inline int micros_pool_release(void *storage, size_t capacity, void *pointer)
{
    if (!pointer) return 1;
    uint8_t *base = storage;
    micros_pool_block_t *previous = NULL;
    for (size_t offset = 0; offset < capacity;) {
        micros_pool_block_t *block = (void *)(base + offset);
        if (!block->span) return 0;
        if ((void *)(block + 1) == pointer) {
            if (!block->used) return 0;
            block->used = 0;
            size_t next_offset = offset + block->span;
            if (next_offset < capacity) {
                micros_pool_block_t *next = (void *)(base + next_offset);
                if (!next->used) block->span += next->span;
            }
            if (previous && !previous->used) previous->span += block->span;
            return 1;
        }
        previous = block;
        offset += block->span;
    }
    return 0;
}
static inline size_t micros_pool_available(void *storage, size_t capacity)
{
    uint8_t *base = storage;
    size_t largest = 0;
    for (size_t offset = 0; offset < capacity;) {
        micros_pool_block_t *block = (void *)(base + offset);
        if (!block->span) return capacity - 16;
        if (!block->used && block->span - 16 > largest) largest = block->span - 16;
        offset += block->span;
    }
    return largest;
}
#endif
