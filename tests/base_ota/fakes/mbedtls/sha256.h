#include <stddef.h>
#include <stdint.h>
/* Deterministic stand-in tests stream accounting, not SHA-256 cryptography. */
typedef struct { uint8_t sum; } mbedtls_sha256_context;
void mbedtls_sha256_init(mbedtls_sha256_context *c);
void mbedtls_sha256_free(mbedtls_sha256_context *c);
int mbedtls_sha256_starts(mbedtls_sha256_context *c,int n);
int mbedtls_sha256_update(mbedtls_sha256_context *c,const void *p,size_t n);
int mbedtls_sha256_finish(mbedtls_sha256_context *c,uint8_t *p);
