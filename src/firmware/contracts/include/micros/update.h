#ifndef MICROS_BASE_OTA_H
#define MICROS_BASE_OTA_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* MBO1: magic, base bytes, image SHA256. */
#define MICROS_BASE_HEADER_BYTES 40u
#define MICROS_BASE_CHUNK_BYTES 4096u
#define MICROS_BASE_TRIAL_SECONDS 180u
void micros_base_boot(void);
int micros_base_application_allowed(const uint8_t graph_hash[32]);
int micros_base_bind_application(unsigned bank, const uint8_t graph_hash[32]);
int micros_base_pending(void);
int micros_base_busy(void);
void micros_base_abort(void);
int micros_base_begin(const uint8_t *header, size_t bytes);
int micros_base_chunk(uint64_t offset, const uint8_t *data, size_t bytes);
int micros_base_finish(void);
int micros_base_confirm(void);
int micros_base_rollback(void);
size_t micros_base_status(char *output, size_t capacity);
#ifdef __cplusplus
}
#endif
#endif
