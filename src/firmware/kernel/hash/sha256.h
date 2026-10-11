#ifndef MICROS_SHA256_H
#define MICROS_SHA256_H
#include <stddef.h>
#include <stdint.h>
typedef struct
{
    uint32_t h[8];
    uint64_t bytes;
    uint8_t block[64];
    size_t used;
} micros_sha256_t;
void micros_sha256_init(micros_sha256_t *state);
void micros_sha256_update(micros_sha256_t *state, const void *data, size_t bytes);
void micros_sha256_finish(micros_sha256_t *state, uint8_t result[32]);
#endif
