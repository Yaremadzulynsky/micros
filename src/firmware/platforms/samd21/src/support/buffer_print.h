#ifndef MICROS_BUFFER_PRINT_H
#define MICROS_BUFFER_PRINT_H
#include "print.h"
class MicrosBufferPrint : public MicrosPrint {
 char *data;size_t capacity,used=0;bool overflow=false;
public:
 MicrosBufferPrint(char *out,size_t bytes):data(out),capacity(bytes) { if(capacity)data[0]=0; }
 size_t write(uint8_t c) override {
  if(used+1>=capacity){overflow=true;return 0;}
  data[used++]=(char)c;data[used]=0;return 1;
 }
 size_t size() const { return overflow?0:used; }
};
#endif
