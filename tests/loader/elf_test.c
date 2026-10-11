#include "elf.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
/* Minimal ELF64: header, two program headers, one dynamic null and one null section. */
enum {
    HEADER = 64,
    PROGRAM = 56,
    DYNAMIC = HEADER + 2 * PROGRAM,
    SECTION = DYNAMIC + 16,
    IMAGE_BYTES = SECTION + 64
};
static void put(uint8_t *destination, uint64_t value, unsigned bytes)
{
    for (unsigned index = 0; index < bytes; ++index)
        destination[index] = (uint8_t)(value >> (8 * index));
}
static void fixture(uint8_t image[IMAGE_BYTES])
{
    memset(image, 0, IMAGE_BYTES);
    put(image, UINT32_C(0x464c457f), 4);
    image[4] = 2;
    image[5] = 1;
    image[6] = 1; /* ELF64, little endian, current. */
    put(image + 16, 3, 2);
    put(image + 18, 62, 2);
    put(image + 20, 1, 4);
    put(image + 32, HEADER, 8);
    put(image + 40, SECTION, 8);
    put(image + 52, HEADER, 2);
    put(image + 54, PROGRAM, 2);
    put(image + 56, 2, 2);
    put(image + 58, 64, 2);
    put(image + 60, 1, 2);
    put(image + HEADER, 1, 4);
    put(image + HEADER + 4, 4, 4); /* Read-only PT_LOAD. */
    put(image + HEADER + 32, IMAGE_BYTES, 8);
    put(image + HEADER + 40, IMAGE_BYTES, 8);
    put(image + HEADER + PROGRAM, 2, 4); /* PT_DYNAMIC. */
    put(image + HEADER + PROGRAM + 8, DYNAMIC, 8);
    put(image + HEADER + PROGRAM + 32, 16, 8);
}
int main(void)
{
    uint8_t valid[IMAGE_BYTES], modified[IMAGE_BYTES];
    fixture(valid);
    assert(!micros_elf_validate(valid, sizeof(valid), 62));
    assert(micros_elf_validate(valid, sizeof(valid), 183));
    for (size_t bytes = 0; bytes < sizeof(valid); ++bytes)
        assert(micros_elf_validate(valid, bytes, 62));
    const unsigned forbidden_tags[] = {1, 12, 13, 25, 26, 27, 28, 32, 33};
    for (size_t index = 0; index < sizeof(forbidden_tags) / sizeof(forbidden_tags[0]); ++index) {
        memcpy(modified, valid, sizeof(valid));
        put(modified + DYNAMIC, forbidden_tags[index], 8);
        put(modified + DYNAMIC + 8, 1, 8);
        assert(micros_elf_validate(modified, sizeof(modified), 62));
    }
    memcpy(modified, valid, sizeof(valid));
    put(modified + HEADER + 4, 7, 4); /* Writable executable mapping. */
    assert(micros_elf_validate(modified, sizeof(modified), 62));
    put(modified + HEADER, 7, 4); /* PT_TLS is outside the service profile. */
    assert(micros_elf_validate(modified, sizeof(modified), 62));
    /* Deterministic mutation corpus exercises parser arithmetic under ASan/UBSan. */
    /* Fixed MCR1-derived seed and Numerical Recipes 32-bit LCG constants make failures replayable. */
    uint32_t random_state = UINT32_C(0x4d435231);
    for (unsigned iteration = 0; iteration < 10000; ++iteration) {
        memcpy(modified, valid, sizeof(valid));
        for (unsigned mutation = 0; mutation < 8; ++mutation) {
            random_state = random_state * UINT32_C(1664525) + UINT32_C(1013904223);
            modified[random_state % sizeof(modified)] ^= (uint8_t)(random_state >> 24);
        }
        (void)micros_elf_validate(modified, sizeof(modified), 62);
    }
    puts("ELF truncation, target, constructor/dependency, W+X, TLS and 10000 mutations passed");
}
