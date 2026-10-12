#ifndef MICROS_INTEGER_H
#define MICROS_INTEGER_H
#include <stdint.h>
#include <stddef.h>
#include <limits.h>
#include <string.h>

/* Protocol integers must not depend on optional libc long-long formatting.
 * Returned text owns its storage; use .text within the same full expression. */
typedef struct { char text[21]; } micros_integer_text_t;
static inline micros_integer_text_t micros_integer_text(uint64_t value, unsigned base)
{
    micros_integer_text_t result = {{0}};
    char reversed[20]; size_t count = 0;
    do { reversed[count++] = "0123456789abcdef"[value % base]; value /= base; } while (value);
    for (size_t i = 0; i < count; ++i) result.text[i] = reversed[count - i - 1];
    return result;
}
static inline micros_integer_text_t micros_decimal(uint64_t value) { return micros_integer_text(value, 10); }
static inline micros_integer_text_t micros_hexadecimal(uint64_t value) { return micros_integer_text(value, 16); }

static inline int micros_parse_prefix(const char **input, const char *prefix)
{
    size_t length = strlen(prefix);
    if (strncmp(*input, prefix, length)) return 0;
    *input += length; return 1;
}
static inline int micros_integer_space(char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; }
/* A complete unsigned token, with explicit overflow and delimiter checks.
 * Failure never advances the input or changes the output. No signs/prefixes. */
static inline int micros_parse_u64(const char **input, unsigned base, uint64_t *value)
{
    const char *p = *input;
    while (*p == ' ' || *p == '\t') ++p;
    const char *start = p; uint64_t number = 0;
    if (base != 10 && base != 16) return 0;
    while (*p && !micros_integer_space(*p)) {
        unsigned digit = *p >= '0' && *p <= '9' ? (unsigned)(*p - '0') :
                         *p >= 'a' && *p <= 'f' ? (unsigned)(*p - 'a' + 10) :
                         *p >= 'A' && *p <= 'F' ? (unsigned)(*p - 'A' + 10) : 16;
        if (digit >= base || number > (UINT64_MAX - digit) / base) return 0;
        number = number * base + digit; ++p;
    }
    if (p == start) return 0;
    *input = p; *value = number; return 1;
}
static inline int micros_parse_unsigned(const char **input, unsigned *value)
{
    const char *p = *input; uint64_t number;
    if (!micros_parse_u64(&p, 10, &number) || number > UINT_MAX) return 0;
    *input = p; *value = (unsigned)number; return 1;
}
static inline int micros_parse_word(const char **input, char *output, size_t capacity)
{
    const char *p = *input;
    while (*p == ' ' || *p == '\t') ++p;
    size_t count = 0;
    while (p[count] && !micros_integer_space(p[count])) ++count;
    if (!count || count >= capacity) return 0;
    for (size_t i = 0; i < count; ++i) output[i] = p[i];
    output[count] = 0; *input = p + count; return 1;
}
static inline int micros_parse_end(const char *input)
{
    while (micros_integer_space(*input)) ++input;
    return !*input;
}
#endif
