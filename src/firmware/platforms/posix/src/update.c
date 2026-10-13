#include <micros/update.h>
#include <stdio.h>
void micros_base_boot(void) {}
int micros_base_application_allowed(const uint8_t hash[32]) { (void)hash;return 1; }
int micros_base_bind_application(unsigned bank,const uint8_t hash[32]) { (void)hash;return bank<2; }
int micros_base_pending(void) { return 0; }
int micros_base_busy(void) { return 0; }
void micros_base_abort(void) {}
int micros_base_begin(const uint8_t *header,size_t bytes) { (void)header;(void)bytes;return 0; }
int micros_base_chunk(uint64_t offset,const uint8_t *data,size_t bytes) { (void)offset;(void)data;(void)bytes;return 0; }
int micros_base_finish(void) { return 0; }
int micros_base_confirm(void) { return 0; }
size_t micros_base_status(char *out,size_t capacity) {
 int n=snprintf(out,capacity,"{\"supported\":false}");
 return n<0 || (size_t)n>=capacity ? 0:(size_t)n;
}

int micros_base_rollback(void) { return 0; }
