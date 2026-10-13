#include "management_auth.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
int main(void)
{
    /* Fixed non-secret test token exercises every compared position. */
    const char token[] = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    char header[] = "Bearer 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    assert(micros_management_authorized(header, sizeof(header) - 1, token));
    for (size_t index = 0; index < sizeof(header) - 1; ++index) {
        header[index] ^= 1;
        assert(!micros_management_authorized(header, sizeof(header) - 1, token));
        header[index] ^= 1;
    }
    for (size_t length = 0; length < sizeof(header) - 1; ++length)
        assert(!micros_management_authorized(header, length, token));
    assert(!micros_management_authorized(header, sizeof(header), token));
    assert(!micros_management_authorized(NULL, sizeof(header) - 1, token));
    puts("Exact bearer authentication rejects every byte mismatch and all truncated/oversized "
         "headers");
}
