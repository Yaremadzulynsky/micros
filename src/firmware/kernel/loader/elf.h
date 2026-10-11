#ifndef MICROS_ELF_PROFILE_H
#define MICROS_ELF_PROFILE_H
#include <stddef.h>
#include <stdint.h>
/** Validate the bounded ELF64 service profile before handing it to the host loader.
 * expected_machine is the platform's ELF e_machine value, not a micros target ID. */
const char *micros_elf_validate(const uint8_t *bytes, size_t size, uint16_t expected_machine);
#endif
