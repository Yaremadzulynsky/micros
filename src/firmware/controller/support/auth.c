#include "management_auth.h"
int micros_management_authorized(const char *header, size_t header_bytes,
                                 const char token[MICROS_MANAGEMENT_TOKEN_BYTES])
{
    static const char prefix[] = "Bearer ";
    if (!header || !token ||
        header_bytes != MICROS_MANAGEMENT_BEARER_BYTES + MICROS_MANAGEMENT_TOKEN_BYTES)
        return 0;
    unsigned difference = 0;
    for (size_t index = 0; index < MICROS_MANAGEMENT_BEARER_BYTES; ++index)
        difference |= (unsigned char)header[index] ^ (unsigned char)prefix[index];
    for (size_t index = 0; index < MICROS_MANAGEMENT_TOKEN_BYTES; ++index)
        difference |= (unsigned char)header[MICROS_MANAGEMENT_BEARER_BYTES + index] ^
                      (unsigned char)token[index];
    return difference == 0;
}
