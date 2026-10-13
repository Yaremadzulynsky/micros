#define _POSIX_C_SOURCE 200809L
#include <micros/transport.h>
#include <micros/platform.h>
#include <sys/select.h>
#include <errno.h>
#include <unistd.h>
static micros_management_handler_t handler;
void micros_management_start(micros_management_handler_t callback) { handler=callback; }
void micros_management_poll(void) {}
int micros_management_execute(micros_management_request_t *request) {
 if (!handler) return 503;
 handler(request);return request->result?409:200;
}
void micros_management_log(const uint8_t *data,size_t bytes) { micros_platform_debug(data,(uint32_t)bytes); }
int micros_controller_read(uint8_t *out,size_t bytes,unsigned timeout_ms) {
 fd_set fds;FD_ZERO(&fds);FD_SET(STDIN_FILENO,&fds);
 struct timeval timeout={timeout_ms/1000,(timeout_ms%1000)*1000};
 int ready=select(STDIN_FILENO+1,&fds,0,0,&timeout);
 if (ready<0) return errno==EINTR?0:-1;
 if (!ready) return 0;
 ssize_t n=read(STDIN_FILENO,out,bytes);
 return n>0?(int)n:-1;
}
size_t micros_transport_write(const void *data,size_t bytes) {
 size_t done=0;
 while (done<bytes) {
  ssize_t n=write(STDOUT_FILENO,(const char*)data+done,bytes-done);
  if (n<0 && errno==EINTR) continue;
  if (n<=0) break;
  done+=(size_t)n;
 }
 return done;
}
void micros_transport_flush(void) {}

size_t micros_transport_read_log(uint8_t *out,size_t capacity) { (void)out;(void)capacity;return 0; }
