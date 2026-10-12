#include "../../src/firmware/kernel/support/integer.h"
#include <assert.h>
#include <stdio.h>

int main(void)
{
    const uint64_t values[] = {0, 1, UINT32_MAX, UINT64_C(4294967296),
        UINT64_C(9223372036854775808), UINT64_MAX};
    const char *decimal[] = {"0", "1", "4294967295", "4294967296", "9223372036854775808", "18446744073709551615"};
    const char *hex[] = {"0", "1", "ffffffff", "100000000", "8000000000000000", "ffffffffffffffff"};
    for (unsigned i = 0; i < sizeof(values)/sizeof(values[0]); ++i) {
        assert(!strcmp(micros_decimal(values[i]).text, decimal[i]));
        assert(!strcmp(micros_hexadecimal(values[i]).text, hex[i]));
        uint64_t parsed = 0; const char *p = decimal[i];
        assert(micros_parse_u64(&p, 10, &parsed) && !*p && parsed == values[i]);
        p = hex[i];
        assert(micros_parse_u64(&p, 16, &parsed) && !*p && parsed == values[i]);
    }
    const char *bad[] = {"", " ", "-1", "+1", "1junk", "18446744073709551616", "999999999999999999999", "0x10", "1.0"};
    for (unsigned i = 0; i < sizeof(bad)/sizeof(bad[0]); ++i) {
        const char *p = bad[i]; uint64_t value = 42;
        assert(!micros_parse_u64(&p, 10, &value) && p == bad[i] && value == 42);
    }
    const char *p = "10000000000000000"; uint64_t value = 0;
    assert(!micros_parse_u64(&p, 16, &value));
    p = "4294967296"; unsigned small = 42;
    assert(!micros_parse_unsigned(&p, &small) && small == 42);
    p = " 123 tail";
    assert(micros_parse_u64(&p, 10, &value) && value == 123 && !strcmp(p, " tail"));
    char token[5]; assert(micros_parse_word(&p, token, sizeof(token)) && !strcmp(token,"tail") && !*p);
    p = "toolong"; assert(!micros_parse_word(&p, token, sizeof(token)));
    char output[64];
    snprintf(output, sizeof(output), "%s:%s", micros_decimal(UINT64_MAX).text, micros_hexadecimal(UINT64_MAX).text);
    assert(!strcmp(output, "18446744073709551615:ffffffffffffffff"));
    puts("portable integers passed");
    return 0;
}
