#include "device_support.h"
#include <micros/transport.h>
#include <micros/controller.h>
static micros_management_handler_t handler;
static MicrosPrint *destination;
extern "C" size_t micros_transport_write(const void *data,size_t bytes) {
 return (destination?*destination:embedded_console()).write((const uint8_t*)data,bytes);
}
extern "C" void micros_transport_flush(void) { if(!destination)embedded_console_flush(); }
extern "C" int micros_controller_read(uint8_t *out,size_t bytes,unsigned timeout_ms) {
 uint64_t until=micros_platform_now_us()+(uint64_t)timeout_ms*1000;
 size_t count=0;
 do {
  while(count<bytes && embedded_console_available()) {
   int value=embedded_console_read();if(value<0)break;out[count++]=(uint8_t)value;
  }
  if(count || !timeout_ms)break;
  micros_controller_yield();
 } while(micros_platform_now_us()<until);
 return (int)count;
}
static char *remote_command(char *line) { return micros_controller_rpc_reply(line, 0); }
extern "C" void micros_management_start(micros_management_handler_t callback) { handler=callback;embedded_network_start(); }
extern "C" void micros_management_poll(void) { embedded_network_poll(remote_command);embedded_base_ota_poll();embedded_idle(); }
extern "C" int micros_management_execute(micros_management_request_t *request) {
 if(!handler)return 503;
 handler(request);return request->result?409:200;
}
extern "C" void micros_management_log(const uint8_t *data,size_t bytes) { embedded_log(data,bytes); }

extern "C" size_t micros_transport_read_log(uint8_t *out,size_t capacity) { return embedded_logs(out,capacity); }
