/* Link-only fixture; never a working platform. */
#include <micros/platform.h>
#include <micros/storage.h>
#include <micros/transport.h>
#include <micros/network.h>
#include <micros/update.h>
#include <micros/telemetry.h>
void micros_base_boot(void) {}
int micros_base_application_allowed(const uint8_t hash[32]) { return 0; }
int micros_base_bind_application(unsigned bank,const uint8_t hash[32]) { return 0; }
int micros_base_pending(void) { return 0; }
int micros_base_busy(void) { return 0; }
void micros_base_abort(void) {}
int micros_base_begin(const uint8_t *header,size_t bytes) { return 0; }
int micros_base_chunk(uint64_t offset,const uint8_t *data,size_t bytes) { return 0; }
int micros_base_finish(void) { return 0; }
int micros_base_confirm(void) { return 0; }
size_t micros_base_status(char *output,size_t capacity) { return 0; }

int micros_base_rollback(void) { return 0; }
