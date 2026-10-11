#ifndef MICROS_ESP8266_BOOT_RECORD_H
#define MICROS_ESP8266_BOOT_RECORD_H
#include <stdint.h>
#include <stddef.h>
#define MICROS_BOOT_ADDRESS 0x100000u
#define MICROS_BOOT_NONE UINT32_MAX
#define MICROS_BASE_BYTES 0xb0000u
/* Two independently erased sectors; newest valid committed record wins. */
typedef struct {
  uint32_t magic, sequence, good, previous, candidate, attempts, crc, commit;
} micros_boot_record_t;
static inline uint32_t micros_boot_crc(const void *data, size_t bytes) {
  const uint8_t *p = (const uint8_t *)data;
  uint32_t crc = UINT32_MAX;
  while (bytes--) {
    crc ^= *p++;
    for (unsigned i = 0; i < 8; ++i)
      crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1)));
  }
  return ~crc;
}
static inline int micros_boot_valid(const micros_boot_record_t *r) {
  return r->magic == 0x3642544d && r->sequence && r->sequence != UINT32_MAX &&
         r->good < 2 && (r->previous < 2 || r->previous == MICROS_BOOT_NONE) &&
         (r->candidate < 2 || r->candidate == MICROS_BOOT_NONE) &&
         (r->candidate == MICROS_BOOT_NONE || r->candidate != r->good) &&
         r->attempts <= 1 && r->commit == 0x54494d43 &&
         r->crc == micros_boot_crc(r, offsetof(micros_boot_record_t, crc));
}
static inline int micros_boot_latest(const micros_boot_record_t r[2]) {
  int a = micros_boot_valid(r), b = micros_boot_valid(r + 1);
  return !a ? (b ? 1 : -1) : (!b || r[0].sequence >= r[1].sequence ? 0 : 1);
}
static inline int micros_boot_seal(micros_boot_record_t *r) {
  if (r->sequence >= UINT32_MAX - 1)
    return 0;
  ++r->sequence;
  r->magic = 0x3642544d;
  r->commit = 0x54494d43;
  r->crc = micros_boot_crc(r, offsetof(micros_boot_record_t, crc));
  return micros_boot_valid(r);
}
#endif
