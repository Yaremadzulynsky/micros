#ifndef MICROS_MANAGEMENT_AUTH_H
#define MICROS_MANAGEMENT_AUTH_H
#include <stddef.h>
/* A provisioning token contains 256 random bits represented by 64 hex characters. */
#define MICROS_MANAGEMENT_TOKEN_BYTES 64u
#define MICROS_MANAGEMENT_BEARER_BYTES 7u /* Exact HTTP Authorization prefix "Bearer ". */
/** Compare an exact bounded bearer header without early exit on secret differences.
 * TLS protects credentials in transit; the token authorizes trusted native service deployment. */
int micros_management_authorized(const char *header, size_t header_bytes,
                                 const char token[MICROS_MANAGEMENT_TOKEN_BYTES]);
#endif
