/* Link-only fixture; never a working platform. */
#include <micros/platform.h>
#include <micros/storage.h>
#include <micros/transport.h>
#include <micros/network.h>
#include <micros/update.h>
#include <micros/telemetry.h>
int micros_controller_read(uint8_t *out,size_t bytes,unsigned timeout) { return 0; }
void micros_management_start(micros_management_handler_t handler) {}
void micros_management_poll(void) {}
int micros_management_execute(micros_management_request_t *request) { return 0; }
void micros_management_log(const uint8_t *message,size_t bytes) {}
size_t micros_transport_write(const void *data,size_t bytes) { return bytes; }
void micros_transport_flush(void) {}

size_t micros_transport_read_log(uint8_t *out,size_t capacity) { return 0; }
