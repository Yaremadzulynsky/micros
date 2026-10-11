#ifndef MICROS_BOARD_STORAGE_H
#define MICROS_BOARD_STORAGE_H
#include "activation.h"
#include "board_profile.h"
#include <micros/deployment.h>
#include <stddef.h>
#include <stdint.h>
/* NOR erase unit is 4 KiB. Each 128 KiB bank has one graph sector followed by
 * four 16 KiB image regions, enough for the 12,352-byte native image bound. */
#define MICROS_STORAGE_SECTOR_BYTES 4096u
#define MICROS_STORAGE_BANK_BYTES (128u * 1024u)
#define MICROS_STORAGE_IMAGE_BYTES (16u * 1024u)
#include <micros/storage.h>
/** Claim immutable bank mappings; release only after all execution has joined. */
int micros_storage_map_bank(unsigned bank, const void **code, const void **rodata);
void micros_storage_unmap_bank(void);
/** All native execution must be paused. Switch aliases at identical virtual
 * addresses, retaining ownership. 1=switched, 0=old mapping restored,
 * -1=unrecoverable mapping failure: reboot before resuming any native code. */
int micros_storage_switch_bank(unsigned bank);
#endif
