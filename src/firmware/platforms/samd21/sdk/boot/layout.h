#ifndef MICROS_SAMD_BOOT_LAYOUT_H
#define MICROS_SAMD_BOOT_LAYOUT_H
#include <stdint.h>
#define SAMD_LAYOUT_VERSION 2u
#define SAMD_SELECTOR_BASE 0x2000u
#define SAMD_SERVICE_JOURNAL 0x3800u
#define SAMD_BASE_JOURNAL 0x3a00u
#define SAMD_SETTINGS_BASE 0x3c00u
#define SAMD_BASE_BYTES 0x14000u
#define SAMD_BASE_ADDRESS(slot) (0x4000u + (slot) * SAMD_BASE_BYTES)
#define SAMD_SERVICE_BASE 0x2c000u
#define SAMD_SERVICE_BANK_BYTES 0xa000u
#define SAMD_SERVICE_SLOT_BYTES 0x2400u
#define SAMD_BOOT_MAGIC 0x3242544du
#define SAMD_NO_SLOT 0xffffffffu
/* Two 256-byte erase rows. One page includes payload, CRC and commit marker. */
typedef struct {
    uint32_t magic, sequence, good, previous, candidate, attempts;
    uint32_t image_bytes[2], image_crc[2];
    uint32_t reserved[4];
    uint32_t crc, commit;
} samd_boot_record_t;
uint32_t samd_boot_crc(const void *data, uint32_t bytes);
int samd_boot_valid(const samd_boot_record_t *record);
int samd_boot_latest(const samd_boot_record_t records[2]);
#endif
