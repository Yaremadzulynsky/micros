#ifndef MICROS_SUPPORT_STORAGE_H
#define MICROS_SUPPORT_STORAGE_H
#include "flash_layout.h"
#include "deployment_record.h"
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Implemented by storage.c and its private helpers. Addresses are native image
 * addresses; compact profiles require directly addressable immutable banks. */
const embedded_graph_t *embedded_graph(uint32_t bank);
uint32_t embedded_image_address(uint32_t bank, uint32_t slot);
void *embedded_image_data(unsigned slot);
void embedded_base_hash(uint8_t hash[32]);
int embedded_flash_erase(uint32_t address, size_t bytes);
int embedded_flash_write(uint32_t address, const uint8_t *data, size_t bytes);
int embedded_pin_valid(unsigned pin);
int embedded_entry_valid(uint32_t entry, uint32_t base, uint32_t bytes);
/* Yield to the scheduler if running; safe before scheduler startup. */
void embedded_storage_yield(void);
/* Private helpers implemented by this platform’s storage.c. */
int embedded_graph_validate(uint32_t bank, uint8_t hash[32]);
int embedded_image_validate(uint32_t bank, uint32_t slot, uint32_t bytes);
#ifdef __cplusplus
}
#endif
#endif
