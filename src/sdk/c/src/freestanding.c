/* Compiler-emitted aggregate initialization/copies need these symbols even with
 * -ffreestanding. Byte loops keep them inside the service image without ROM or
 * libc imports. Compile with -fno-builtin and no loop-to-library substitution. */
#include <stddef.h>

/** @brief Fill caller-owned storage; minimal freestanding compiler support. */
void *memset(void *destination, int value, size_t bytes)
{
    unsigned char *output = destination;
    for (size_t index = 0; index < bytes; ++index)
        output[index] = (unsigned char)value;
    return destination;
}

/** @brief Copy nonoverlapping caller-owned storage, as required by C aggregates. */
void *memcpy(void *destination, const void *source, size_t bytes)
{
    unsigned char *output = destination;
    const unsigned char *input = source;
    for (size_t index = 0; index < bytes; ++index)
        output[index] = input[index];
    return destination;
}
