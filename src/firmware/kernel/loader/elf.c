#include "elf.h"
/* Layout and tags follow the System V ELF gABI, ELF64 little-endian profile:
 * https://refspecs.linuxfoundation.org/elf/gabi4+/ch4.eheader.html
 * https://refspecs.linuxfoundation.org/elf/gabi4+/ch5.dynamic.html */
#define ELF_HEADER_BYTES 64u
#define ELF_PROGRAM_BYTES 56u
#define ELF_SECTION_BYTES 64u
#define ELF_SYMBOL_BYTES 24u
#define ELF_DYNAMIC_BYTES 16u
#define ELF_MEMORY_LIMIT (4u * 1024u * 1024u) /* Match the bounded host native-image class. */
static uint16_t word16(const uint8_t *bytes)
{
    return (uint16_t)bytes[0] | (uint16_t)bytes[1] << 8;
}
static uint32_t word32(const uint8_t *bytes)
{
    return (uint32_t)word16(bytes) | (uint32_t)word16(bytes + 2) << 16;
}
static uint64_t word64(const uint8_t *bytes)
{
    return (uint64_t)word32(bytes) | (uint64_t)word32(bytes + 4) << 32;
}
static int in_file(uint64_t offset, uint64_t bytes, size_t size)
{
    return offset <= size && bytes <= size - offset;
}
const char *micros_elf_validate(const uint8_t *bytes, size_t size, uint16_t expected_machine)
{
    /* ELF magic, ELFCLASS64=2, ELFDATA2LSB=1, EV_CURRENT=1, ET_DYN=3. */
    if (size < ELF_HEADER_BYTES || word32(bytes) != UINT32_C(0x464c457f) || bytes[4] != 2 ||
        bytes[5] != 1 || bytes[6] != 1 || word16(bytes + 16) != 3 ||
        word16(bytes + 18) != expected_machine || word32(bytes + 20) != 1 ||
        word16(bytes + 52) != ELF_HEADER_BYTES)
        return "ELF64 profile";
    uint64_t program_offset = word64(bytes + 32), section_offset = word64(bytes + 40);
    size_t programs = word16(bytes + 56), sections = word16(bytes + 60);
    if (!programs || word16(bytes + 54) != ELF_PROGRAM_BYTES ||
        !in_file(program_offset, programs * ELF_PROGRAM_BYTES, size) || !sections ||
        word16(bytes + 58) != ELF_SECTION_BYTES ||
        !in_file(section_offset, sections * ELF_SECTION_BYTES, size))
        return "ELF tables";
    uint64_t loaded_bytes = 0, lowest_address = UINT64_MAX, highest_address = 0;
    unsigned dynamic_tables = 0;
    for (size_t index = 0; index < programs; ++index) {
        const uint8_t *program = bytes + program_offset + index * ELF_PROGRAM_BYTES;
        uint32_t type = word32(program), flags = word32(program + 4);
        uint64_t offset = word64(program + 8), file_bytes = word64(program + 32),
                 memory_bytes = word64(program + 40);
        if (!in_file(offset, file_bytes, size))
            return "ELF segment range";
        if (type == 3 || type == 7)
            return "ELF interpreter or TLS"; /* PT_INTERP / PT_TLS. */
        if (type == 1) { /* PT_LOAD: reject W+X segments and unbounded mapped/BSS memory. */
            uint64_t address = word64(program + 16);
            if (file_bytes > memory_bytes || memory_bytes > ELF_MEMORY_LIMIT - loaded_bytes ||
                (flags & 3u) == 3u)
                return "ELF load memory";
            if (address > UINT64_MAX - memory_bytes)
                return "ELF virtual address overflow";
            if (address < lowest_address)
                lowest_address = address;
            if (address + memory_bytes > highest_address)
                highest_address = address + memory_bytes;
            if (highest_address - lowest_address > ELF_MEMORY_LIMIT)
                return "ELF mapped span";
            loaded_bytes += memory_bytes;
        }
        if (type ==
            2) { /* PT_DYNAMIC: constructors and dependency code must not run during dlopen. */
            if (++dynamic_tables != 1 || file_bytes % ELF_DYNAMIC_BYTES)
                return "ELF dynamic table";
            int terminated = 0;
            for (uint64_t entry = 0; entry < file_bytes; entry += ELF_DYNAMIC_BYTES) {
                uint64_t tag = word64(bytes + offset + entry),
                         value = word64(bytes + offset + entry + 8);
                if (tag == 0) {
                    terminated = 1;
                    break;
                } /* DT_NULL terminates entries. */
                /* DT_NEEDED, INIT, FINI, INIT_ARRAY, FINI_ARRAY, PREINIT_ARRAY
                 * and their sizes. No implicit startup/shutdown or imported libraries. */
                if (tag == 1 || (value && (tag == 12 || tag == 13 || (tag >= 25 && tag <= 28) ||
                                           tag == 32 || tag == 33)))
                    return "ELF constructors or dependencies";
                /* GNU audit/filter dependency hooks and NODELETE / STATIC_TLS flags. */
                if (tag == UINT64_C(0x6ffffefb) || tag == UINT64_C(0x6ffffefc) ||
                    tag == UINT64_C(0x7ffffffd) || tag == UINT64_C(0x7fffffff) ||
                    (tag == UINT64_C(0x6ffffffb) && (value & 8u)) || (tag == 30 && (value & 16u)))
                    return "ELF unsupported dynamic behavior";
            }
            if (!terminated)
                return "ELF unterminated dynamic table";
        }
    }
    if (!loaded_bytes || dynamic_tables != 1)
        return "ELF missing load/dynamic segment";
    for (size_t index = 0; index < sections; ++index) {
        const uint8_t *section = bytes + section_offset + index * ELF_SECTION_BYTES;
        uint32_t type = word32(section + 4);
        uint64_t flags = word64(section + 8), offset = word64(section + 24),
                 section_bytes = word64(section + 32);
        /* SHT_NOBITS=8 has no file payload; SHF_TLS=0x400. */
        if (type != 8 && !in_file(offset, section_bytes, size))
            return "ELF section range";
        if ((flags & UINT64_C(0x400)) || (section_bytes && type >= 14 && type <= 16))
            return "ELF initialization section or TLS";
        if (type == 11) { /* SHT_DYNSYM entries: no undefined imports, TLS or IFUNC resolvers. */
            if (word64(section + 56) != ELF_SYMBOL_BYTES || section_bytes % ELF_SYMBOL_BYTES)
                return "ELF dynamic symbols";
            for (uint64_t entry = 0; entry < section_bytes; entry += ELF_SYMBOL_BYTES) {
                const uint8_t *symbol = bytes + offset + entry;
                unsigned symbol_type = symbol[4] & 15u; /* ELF64_ST_TYPE is the low nibble. */
                if ((word32(symbol) && word16(symbol + 6) == 0) || symbol_type == 6 ||
                    symbol_type == 10)
                    return "ELF import, TLS or resolver symbol";
            }
        }
        if (type ==
            4) { /* SHT_RELA: only ordinary data/pointer relocations, never IRELATIVE code. */
            if (word64(section + 56) != 24u || section_bytes % 24u)
                return "ELF relocation table"; /* Elf64_Rela is three eight-byte fields. */
            for (uint64_t entry = 0; entry < section_bytes; entry += 24u) {
                uint32_t relocation = (uint32_t)word64(bytes + offset + entry + 8);
                /* x86-64: 64, GLOB_DAT, JUMP_SLOT, RELATIVE. AArch64 equivalents below. */
                int ordinary =
                    expected_machine == 62
                        ? relocation == 1 || relocation == 6 || relocation == 7 || relocation == 8
                        : relocation == 257 || relocation == 1025 || relocation == 1026 ||
                              relocation == 1027;
                if (!ordinary)
                    return "ELF unsupported relocation";
            }
        }
        if (type == 9 && section_bytes)
            return "ELF REL unsupported; use RELA";
    }
    return NULL;
}
