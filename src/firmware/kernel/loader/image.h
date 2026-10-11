#ifndef MICROS_IMAGE_H
#define MICROS_IMAGE_H
#include <micros/service.h>
#include <stddef.h>
#include <stdint.h>
/* Format 1 is sixteen little-endian uint32_t words: 16 * 4 = 64 bytes.
 * This is a serialized layout, never sizeof a pointer-bearing native struct. */
#define MICROS_IMAGE_HEADER_BYTES 64u

/* Bytes 4d 43 52 31 spell "MCR1" on disk. The uint32_t value is little-endian. */
#define MICROS_IMAGE_MAGIC UINT32_C(0x3152434d)

/* Format identifier for the M1 envelope; unrelated to service ABI revision. */
#define MICROS_IMAGE_FORMAT_VERSION 1u
#define MICROS_IMAGE_FLASH_FORMAT_VERSION 2u

/* Defensive host-side file/allocation cap for the experiment. 4 MiB is a
 * deliberately generous policy ceiling, NOT available ESP32 execution RAM.
 * The MCU additionally checks its much smaller staging and slot capacities. */
#define MICROS_IMAGE_LIMIT (4u * 1024u * 1024u)

/* Wire word alignment permits ESP32 IRAM's required aligned 32-bit stores. */
#define MICROS_IMAGE_WORD_BYTES 4u

/* Experimental Xtensa descriptor: eight uint32 fields + four 32-bit hooks. */
#define MICROS_XTENSA_DESCRIPTOR_BYTES 48u

/* Byte offsets of the sixteen wire words. Format 1 reserves the last four;
 * format 2 uses words 12/13 for the read-only alias and suffix length.
 * See docs/archive/documentation/architecture/native-image.md for the field definitions. */
enum micros_image_field_offset {
    MICROS_IMAGE_MAGIC_OFFSET = 0,
    MICROS_IMAGE_FORMAT_OFFSET = 4,
    MICROS_IMAGE_TARGET_OFFSET = 8,
    MICROS_IMAGE_ABI_MAJOR_OFFSET = 12,
    MICROS_IMAGE_ABI_REVISION_OFFSET = 16,
    MICROS_IMAGE_CODE_BASE_OFFSET = 20,
    MICROS_IMAGE_DATA_BASE_OFFSET = 24,
    MICROS_IMAGE_CODE_BYTES_OFFSET = 28,
    MICROS_IMAGE_DATA_BYTES_OFFSET = 32,
    MICROS_IMAGE_BSS_BYTES_OFFSET = 36,
    MICROS_IMAGE_DESCRIPTOR_OFFSET = 40,
    MICROS_IMAGE_CHECKSUM_OFFSET = 44,
    MICROS_IMAGE_RESERVED_OFFSET = 48,
    MICROS_IMAGE_RODATA_BASE_OFFSET = 48,
    MICROS_IMAGE_RODATA_BYTES_OFFSET = 52,
    MICROS_IMAGE_FLASH_RESERVED_OFFSET = 56
};

/**
 * @brief Decoded image layout returned by successful envelope validation.
 *
 * Stores scalar metadata, not payload pointers or the serialized header itself.
 * ESP32 loaders use the addresses and lengths to place code, data, and BSS;
 * host images carry a Mach-O library in the code payload with other fields zero.
 * Validation of this layout does not replace native descriptor validation.
 */
typedef struct {
    /** Native target profile identified by MICROS_TARGET_* values. */
    uint32_t target;
    /** ESP32 code load address; zero for host images. */
    uint32_t code_base;
    /** ESP32 initialized-data load address; zero for host images. */
    uint32_t data_base;
    /** Code payload length in bytes, or the entire host library length. */
    uint32_t code_bytes;
    /** Initialized-data payload length in bytes, following the code payload. */
    uint32_t data_bytes;
    /** Zero-filled storage length in bytes, placed after initialized data. */
    uint32_t bss_bytes;
    /** Byte offset of the ESP32 native descriptor within initialized data. */
    uint32_t descriptor_offset;
    /** Format 2: read-only alias of the combined text/constant payload. */
    uint32_t rodata_base, rodata_bytes;
} micros_image_t;
uint32_t micros_crc32(const uint8_t *data, size_t size);
const char *micros_image_validate(const uint8_t *bytes, size_t size, uint32_t target,
                                  micros_image_t *validated_image);
const char *micros_descriptor_validate(const micros_service_descriptor_t *descriptor,
                                       uint32_t target);
#endif
