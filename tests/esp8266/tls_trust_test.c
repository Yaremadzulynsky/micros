/* Run with the pinned, patched Mbed TLS libraries and generated relay-der.h.
 * AddressSanitizer checks ownership and cleanup of immutable trust buffers. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "mbedtls/x509_crt.h"
#include "relay-der.h"
const unsigned char micros_relay_pem[] = "test marker";
int main(int argc, char **argv) {
 assert(argc == 2);
 mbedtls_x509_crt flash, copied;
 mbedtls_x509_crt_init(&flash); mbedtls_x509_crt_init(&copied);
 assert(micros_parse_relay_ca(&flash, micros_relay_pem, sizeof(micros_relay_pem)) == 0);
 assert(mbedtls_x509_crt_parse_file(&copied, argv[1]) == 0);
 size_t roots = 0, saved = 0;
 for (mbedtls_x509_crt *a=&flash, *b=&copied; a; a=a->next, b=b->next) {
  assert(b && !a->own_buffer && b->own_buffer);
  assert(a->raw.len == b->raw.len && !memcmp(a->raw.p,b->raw.p,a->raw.len));
  assert(a->pk.pk_info == b->pk.pk_info);
  uint32_t f1=0,f2=0;
  int r1=mbedtls_x509_crt_verify(a,a,NULL,NULL,&f1,NULL,NULL);
  int r2=mbedtls_x509_crt_verify(b,b,NULL,NULL,&f2,NULL,NULL);
  assert(r1 == r2 && f1 == f2);
  r1=mbedtls_x509_crt_verify(a,a,NULL,"unrelated.invalid",&f1,NULL,NULL);
  r2=mbedtls_x509_crt_verify(b,b,NULL,"unrelated.invalid",&f2,NULL,NULL);
  assert(r1 != 0 && r1 == r2 && f1 == f2);
  assert(f1 & MBEDTLS_X509_BADCERT_CN_MISMATCH);
  saved += a->raw.len; roots++;
  if (!a->next) assert(!b->next);
 }
 mbedtls_x509_crt_free(&flash); mbedtls_x509_crt_free(&copied);
 /* Unrelated input must still use the copying parser. */
 assert(micros_parse_relay_ca(&copied, micros_root_0, sizeof(micros_root_0)) == 0);
 assert(copied.own_buffer && copied.raw.p != micros_root_0);
 mbedtls_x509_crt_free(&copied);
 const unsigned char malformed[] = {0x30,0x03,0x01,0x01,0x00};
 assert(mbedtls_x509_crt_parse_der_nocopy(&flash,malformed,sizeof(malformed)) != 0);
 mbedtls_x509_crt_free(&flash);
 printf("Verified %zu unchanged trust anchors; %zu DER bytes remain in flash.\n",roots,saved);
}
