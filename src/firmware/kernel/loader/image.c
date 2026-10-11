#include "image.h"
#include "elf.h"
#include "m1_limits.h"

/* Bytes are 8 bits: shifts 0/8/16/24 reconstruct a little-endian 32-bit word.
 * Two such words, four bytes apart, reconstruct a 64-bit value with a 32-bit shift. */
static uint32_t read_u32_le(const uint8_t *encoded_bytes)
{
    return (uint32_t)encoded_bytes[0] | (uint32_t)encoded_bytes[1] << 8 |
           (uint32_t)encoded_bytes[2] << 16 | (uint32_t)encoded_bytes[3] << 24;
}
static uint64_t read_u64_le(const uint8_t *encoded_bytes)
{
    return (uint64_t)read_u32_le(encoded_bytes) | (uint64_t)read_u32_le(encoded_bytes + 4) << 32;
}
/* Mach-O constants/layout from Apple's mach-o/loader.h and mach/machine.h.
 * Kept local so the shared validator also compiles without macOS SDK headers.
 * These values describe Apple's file format; they are not micros policy. */
#define MACHO_MAGIC_64 UINT32_C(0xfeedfacf)  /* MH_MAGIC_64, little-endian 64-bit file. */
#define MACHO_CPU_ARM64 UINT32_C(0x0100000c) /* CPU_ARCH_ABI64 | CPU_TYPE_ARM (12). */
enum {
    MACHO_FILE_DYLIB = 6,             /* MH_DYLIB: a dynamically bound shared library. */
    MACHO_COMMAND_SEGMENT_64 = 0x19,  /* LC_SEGMENT_64: section table follows. */
    MACHO_COMMAND_ROUTINES_64 = 0x1a, /* LC_ROUTINES_64: unsupported init routine. */
    MACHO_SECTION_ZERO_FILL = 1,      /* S_ZEROFILL has no bytes in the file. */
    MACHO_SECTION_INIT_POINTERS = 9,  /* S_MOD_INIT_FUNC_POINTERS. */
    MACHO_SECTION_TERM_POINTERS = 10, /* S_MOD_TERM_FUNC_POINTERS. */
    MACHO_SECTION_TLS_FIRST = 17,     /* S_THREAD_LOCAL_REGULAR starts TLS types. */
    MACHO_SECTION_TLS_LAST = 21,      /* S_THREAD_LOCAL_INIT_FUNCTION_POINTERS. */
    MACHO_SECTION_TYPE_MASK = 0xff,   /* Low 8 flag bits encode section type. */

    /* mach_header_64: eight uint32 fields; load commands begin at byte 32. */
    MACHO_HEADER_BYTES = 32,
    MACHO_CPU_OFFSET = 4,
    MACHO_FILE_TYPE_OFFSET = 12,
    MACHO_COMMAND_COUNT_OFFSET = 16,
    MACHO_COMMAND_BYTES_OFFSET = 20,

    /* load_command: uint32 command + uint32 size, with 8-byte 64-bit alignment. */
    MACHO_COMMAND_HEADER_BYTES = 8,
    MACHO_COMMAND_ALIGNMENT = 8,
    MACHO_COMMAND_SIZE_OFFSET = 4,

    /* segment_command_64 layout; its section_64 array starts after 72 bytes. */
    MACHO_SEGMENT_BYTES = 72,
    MACHO_SEGMENT_FILE_OFFSET = 40,
    MACHO_SEGMENT_FILE_BYTES_OFFSET = 48,
    MACHO_SEGMENT_SECTION_COUNT_OFFSET = 64,

    /* section_64 has two 16-byte names, address/size, and eight uint32 fields. */
    MACHO_SECTION_BYTES = 80,
    MACHO_SECTION_SIZE_OFFSET = 40,
    MACHO_SECTION_FILE_OFFSET = 48,
    MACHO_SECTION_FLAGS_OFFSET = 64
};

/* Validate nested file ranges before handing the payload to the native loader. */
static const char *macho_validate(const uint8_t *image_bytes, size_t image_size)
{
    if (image_size < MACHO_HEADER_BYTES || read_u32_le(image_bytes) != MACHO_MAGIC_64 ||
        read_u32_le(image_bytes + MACHO_CPU_OFFSET) != MACHO_CPU_ARM64 ||
        read_u32_le(image_bytes + MACHO_FILE_TYPE_OFFSET) != MACHO_FILE_DYLIB)
        return "Mach-O profile";
    size_t command_count = read_u32_le(image_bytes + MACHO_COMMAND_COUNT_OFFSET),
           command_bytes = read_u32_le(image_bytes + MACHO_COMMAND_BYTES_OFFSET),
           command_offset = MACHO_HEADER_BYTES;
    if (command_bytes > image_size - MACHO_HEADER_BYTES ||
        command_count > command_bytes / MACHO_COMMAND_HEADER_BYTES)
        return "Mach-O commands";
    size_t commands_end = MACHO_HEADER_BYTES + command_bytes;
    for (size_t command_index = 0; command_index < command_count; ++command_index) {
        if (command_offset > commands_end ||
            commands_end - command_offset < MACHO_COMMAND_HEADER_BYTES)
            return "Mach-O command bounds";
        const uint8_t *command = image_bytes + command_offset;
        size_t command_size = read_u32_le(command + MACHO_COMMAND_SIZE_OFFSET);
        if (command_size < MACHO_COMMAND_HEADER_BYTES ||
            (command_size & (MACHO_COMMAND_ALIGNMENT - 1)) ||
            command_size > commands_end - command_offset)
            return "Mach-O command size";
        if (read_u32_le(command) == MACHO_COMMAND_ROUTINES_64)
            return "Mach-O initialization routine";
        if (read_u32_le(command) == MACHO_COMMAND_SEGMENT_64) {
            if (command_size < MACHO_SEGMENT_BYTES)
                return "Mach-O segment";
            uint64_t segment_file_offset = read_u64_le(command + MACHO_SEGMENT_FILE_OFFSET),
                     segment_file_bytes = read_u64_le(command + MACHO_SEGMENT_FILE_BYTES_OFFSET);
            if (segment_file_offset > image_size ||
                segment_file_bytes > image_size - segment_file_offset)
                return "Mach-O segment range";
            size_t section_count = read_u32_le(command + MACHO_SEGMENT_SECTION_COUNT_OFFSET);
            if (section_count > (command_size - MACHO_SEGMENT_BYTES) / MACHO_SECTION_BYTES)
                return "Mach-O sections";
            for (size_t section_index = 0; section_index < section_count; ++section_index) {
                const uint8_t *section =
                    command + MACHO_SEGMENT_BYTES + section_index * MACHO_SECTION_BYTES;
                unsigned section_type =
                    read_u32_le(section + MACHO_SECTION_FLAGS_OFFSET) & MACHO_SECTION_TYPE_MASK;
                if (section_type == MACHO_SECTION_INIT_POINTERS ||
                    section_type == MACHO_SECTION_TERM_POINTERS ||
                    (section_type >= MACHO_SECTION_TLS_FIRST &&
                     section_type <= MACHO_SECTION_TLS_LAST))
                    return "Mach-O constructors or TLS";
                uint64_t section_size = read_u64_le(section + MACHO_SECTION_SIZE_OFFSET),
                         section_file_offset = read_u32_le(section + MACHO_SECTION_FILE_OFFSET);
                if (section_type != MACHO_SECTION_ZERO_FILL &&
                    (section_file_offset > image_size ||
                     section_size > image_size - section_file_offset))
                    return "Mach-O section range";
            }
        }
        command_offset += command_size;
    }
    return command_offset == commands_end ? NULL : "Mach-O command total";
}
/* Reflected CRC-32/ISO-HDLC polynomial (the bit-reversed 0x04c11db7),
 * initial all-ones register, and final inversion match zlib.crc32.
 * Eight one-bit rounds consume each 8-bit byte. This is not authentication. */
#define MICROS_CRC32_REFLECTED_POLYNOMIAL UINT32_C(0xedb88320)
uint32_t micros_crc32(const uint8_t *payload, size_t payload_size)
{
    uint32_t checksum = UINT32_MAX;
    for (size_t byte_index = 0; byte_index < payload_size; ++byte_index) {
        checksum ^= payload[byte_index];
        for (unsigned bit_index = 0; bit_index < 8; ++bit_index)
            checksum =
                (checksum >> 1) ^ (MICROS_CRC32_REFLECTED_POLYNOMIAL & (0u - (checksum & 1u)));
    }
    return ~checksum;
}
const char *micros_image_validate(const uint8_t *image_bytes, size_t image_size, uint32_t target,
                                  micros_image_t *validated_image)
{
    if (image_size < MICROS_IMAGE_HEADER_BYTES || image_size > MICROS_IMAGE_LIMIT)
        return "image length";
    uint32_t format = read_u32_le(image_bytes + MICROS_IMAGE_FORMAT_OFFSET);
    if (read_u32_le(image_bytes) != MICROS_IMAGE_MAGIC ||
        (format != MICROS_IMAGE_FORMAT_VERSION &&
         !(format == MICROS_IMAGE_FLASH_FORMAT_VERSION && target == MICROS_TARGET_ESP32_XTENSA)))
        return "image format";
    if (read_u32_le(image_bytes + MICROS_IMAGE_TARGET_OFFSET) != target)
        return "target mismatch";
    if (read_u32_le(image_bytes + MICROS_IMAGE_ABI_MAJOR_OFFSET) != MICROS_ABI_MAJOR ||
        read_u32_le(image_bytes + MICROS_IMAGE_ABI_REVISION_OFFSET) != MICROS_ABI_REVISION)
        return "ABI mismatch";
    for (unsigned reserved_offset = format == MICROS_IMAGE_FLASH_FORMAT_VERSION
             ? MICROS_IMAGE_FLASH_RESERVED_OFFSET : MICROS_IMAGE_RESERVED_OFFSET;
         reserved_offset < MICROS_IMAGE_HEADER_BYTES; reserved_offset += MICROS_IMAGE_WORD_BYTES)
        if (read_u32_le(image_bytes + reserved_offset))
            return "reserved field";
    micros_image_t image_header = {read_u32_le(image_bytes + MICROS_IMAGE_TARGET_OFFSET),
                                   read_u32_le(image_bytes + MICROS_IMAGE_CODE_BASE_OFFSET),
                                   read_u32_le(image_bytes + MICROS_IMAGE_DATA_BASE_OFFSET),
                                   read_u32_le(image_bytes + MICROS_IMAGE_CODE_BYTES_OFFSET),
                                   read_u32_le(image_bytes + MICROS_IMAGE_DATA_BYTES_OFFSET),
                                   read_u32_le(image_bytes + MICROS_IMAGE_BSS_BYTES_OFFSET),
                                   read_u32_le(image_bytes + MICROS_IMAGE_DESCRIPTOR_OFFSET),
                                   format == MICROS_IMAGE_FLASH_FORMAT_VERSION
                                       ? read_u32_le(image_bytes + MICROS_IMAGE_RODATA_BASE_OFFSET) : 0,
                                   format == MICROS_IMAGE_FLASH_FORMAT_VERSION
                                       ? read_u32_le(image_bytes + MICROS_IMAGE_RODATA_BYTES_OFFSET) : 0};
    if (format == MICROS_IMAGE_FLASH_FORMAT_VERSION && (!image_header.rodata_base ||
        (image_header.rodata_base | image_header.rodata_bytes) % 4 ||
        image_header.rodata_bytes >= image_header.code_bytes ||
        image_header.code_bytes > UINT32_MAX - image_header.rodata_base))
        return "flash layout";
    if (!image_header.code_bytes ||
        image_header.code_bytes > image_size - MICROS_IMAGE_HEADER_BYTES ||
        image_header.data_bytes != image_size - MICROS_IMAGE_HEADER_BYTES - image_header.code_bytes)
        return "section length";
    if (micros_crc32(image_bytes + MICROS_IMAGE_HEADER_BYTES,
                     image_size - MICROS_IMAGE_HEADER_BYTES) !=
        read_u32_le(image_bytes + MICROS_IMAGE_CHECKSUM_OFFSET))
        return "payload checksum";
    if (target == MICROS_TARGET_MACOS_ARM64 || target == MICROS_TARGET_LINUX_ARM64 ||
        target == MICROS_TARGET_LINUX_X86_64) {
        if (image_header.code_base || image_header.data_base || image_header.data_bytes ||
            image_header.bss_bytes || image_header.descriptor_offset)
            return "host image layout";
        /* Reject non-arm64/non-dylib inputs before invoking the native loader. */
        const char *error =
            target == MICROS_TARGET_MACOS_ARM64
                ? macho_validate(image_bytes + MICROS_IMAGE_HEADER_BYTES, image_header.code_bytes)
                : micros_elf_validate(image_bytes + MICROS_IMAGE_HEADER_BYTES,
                                      image_header.code_bytes,
                                      target == MICROS_TARGET_LINUX_ARM64 ? 183 : 62);
        if (error)
            return error;
    } else if (target == MICROS_TARGET_ESP32_XTENSA) {
        if ((image_header.code_base | image_header.data_base | image_header.code_bytes |
             image_header.data_bytes | image_header.bss_bytes | image_header.descriptor_offset) &
            (MICROS_IMAGE_WORD_BYTES - 1u))
            return "section alignment";
        /* 32-bit Xtensa descriptor consists of 8 words + 4 function pointers. */
        if (image_header.data_bytes < MICROS_XTENSA_DESCRIPTOR_BYTES ||
            image_header.descriptor_offset >
                image_header.data_bytes - MICROS_XTENSA_DESCRIPTOR_BYTES)
            return "descriptor offset";
        if (image_header.code_bytes > UINT32_MAX - image_header.code_base ||
            image_header.data_bytes > UINT32_MAX - image_header.data_base ||
            image_header.bss_bytes > UINT32_MAX - image_header.data_base - image_header.data_bytes)
            return "address overflow";
    } else if (target == MICROS_TARGET_ARMV6M || target == MICROS_TARGET_ESP8266_XTENSA) {
        if ((image_header.code_base | image_header.data_base | image_header.code_bytes |
             image_header.data_bytes | image_header.bss_bytes | image_header.descriptor_offset) & 3u)
            return "section alignment";
        if (image_header.data_bytes < 48u || image_header.descriptor_offset > image_header.data_bytes - 48u)
            return "descriptor offset";
        if (image_header.code_bytes > UINT32_MAX - image_header.code_base ||
            image_header.data_bytes > UINT32_MAX - image_header.data_base ||
            image_header.bss_bytes > UINT32_MAX - image_header.data_base - image_header.data_bytes)
            return "address overflow";
    } else
        return "unsupported target";
    *validated_image = image_header;
    return NULL;
}
const char *micros_descriptor_validate(const micros_service_descriptor_t *descriptor,
                                       uint32_t target)
{
    if (!descriptor || descriptor->struct_bytes != sizeof(*descriptor))
        return "descriptor size";
    if (descriptor->target != target || descriptor->abi_major != MICROS_ABI_MAJOR ||
        descriptor->abi_revision != MICROS_ABI_REVISION)
        return "descriptor compatibility";
    if (descriptor->reserved > 1 || !descriptor->init || !descriptor->start || !descriptor->step ||
        !descriptor->stop)
        return "descriptor hooks";
    if (!descriptor->arena_alignment ||
        (descriptor->arena_alignment & (descriptor->arena_alignment - 1)) ||
        descriptor->arena_alignment > MICROS_M1_SLOT_ALIGNMENT ||
        descriptor->arena_bytes > MICROS_M1_ARENA_BYTES ||
        !descriptor->stack_bytes ||
        descriptor->stack_bytes > MICROS_M1_MAX_STACK_BYTES)
        return "descriptor budget";
    return NULL;
}
