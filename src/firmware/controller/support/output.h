#ifndef MICROS_CONTROLLER_OUTPUT_H
#define MICROS_CONTROLLER_OUTPUT_H
#include <micros/transport.h>
#include <stdarg.h>
#include <stdio.h>
/* Bound each formatting fragment; status is emitted as multiple fragments. */
static int controller_printf(const char *format, ...) __attribute__((format(printf,1,2)));
static int controller_printf(const char *format, ...) {
 char text[1024];va_list args;va_start(args,format);
 int n=vsnprintf(text,sizeof(text),format,args);va_end(args);
 if(n<0 || (size_t)n>=sizeof(text))return -1;
 return micros_transport_write(text,(size_t)n)==(size_t)n?n:-1;
}
static int controller_puts(const char *text) {
 size_t n=strlen(text);return micros_transport_write(text,n)==n && micros_transport_write("\n",1)==1?0:-1;
}
static void controller_event(const char *format, ...) __attribute__((format(printf,1,2)));
static void controller_event(const char *format, ...) {
 char text[256];va_list args;va_start(args,format);
 int n=vsnprintf(text,sizeof(text),format,args);va_end(args);
 if(n>0 && (size_t)n<sizeof(text))micros_platform_debug((const uint8_t*)text,(uint32_t)n);
}
#define printf controller_printf
#define puts controller_puts
#define fflush(stream) micros_transport_flush()
#endif
