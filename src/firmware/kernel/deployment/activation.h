#ifndef MICROS_ACTIVATION_H
#define MICROS_ACTIVATION_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Two independent flash erase sectors retain the last complete selection while
 * its successor is written. The commit word is programmed only after its CRC. */
#define MICROS_ACTIVATION_MAGIC UINT32_C(0x3141434d)  /* MCA1, little endian. */
#define MICROS_ACTIVATION_COMMIT UINT32_C(0x54494d43) /* CMIT: written last. */
#define MICROS_ACTIVATION_NONE UINT32_MAX
#define MICROS_ACTIVATION_ATTEMPTS 2u    /* A candidate gets at most two boot trials. */
#define MICROS_ACTIVATION_HASH_BYTES 32u /* SHA-256 identity of graph and referenced images. */
/** @brief Atomic selection binding known-good, retained and trial banks to exact content. */
typedef struct {
    uint32_t magic, sequence, good, previous, candidate, attempts, pending;
    uint8_t good_hash[MICROS_ACTIVATION_HASH_BYTES];
    uint8_t previous_hash[MICROS_ACTIVATION_HASH_BYTES];
    uint8_t candidate_hash[MICROS_ACTIVATION_HASH_BYTES];
    uint32_t checksum, commit;
} micros_activation_record_t;
#ifdef __cplusplus
static_assert(sizeof(micros_activation_record_t) == 132,
               "seven words, three SHA-256 hashes, CRC and commit");
#else
_Static_assert(sizeof(micros_activation_record_t) == 132,
               "seven words, three SHA-256 hashes, CRC and commit");
#endif
/** Validate format, bounds, CRC and final commit marker without touching storage. */
int micros_activation_valid(const micros_activation_record_t *record);
/** Return the newest complete sector index, or -1 when physical recovery is needed. */
int micros_activation_latest(const micros_activation_record_t records[2]);
/** Create the empty recovery selection; no service is trusted until its first healthy trial. */
micros_activation_record_t micros_activation_empty(void);
/** Seal a successor; sequence exhaustion is rejected instead of wrapping. */
int micros_activation_seal(micros_activation_record_t *next, uint32_t previous_sequence);
/** Bank selected for this boot; exhausted trials fall back to known-good. */
uint32_t micros_activation_boot_bank(const micros_activation_record_t *record);
#ifdef __cplusplus
}
#endif
#endif
