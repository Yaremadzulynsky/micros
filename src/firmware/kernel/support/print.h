#ifndef MICROS_EMBEDDED_PRINT_H
#define MICROS_EMBEDDED_PRINT_H
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
class MicrosPrint {
public:
  virtual ~MicrosPrint() = default;
  virtual size_t write(uint8_t c) = 0;
  virtual size_t write(const uint8_t *data, size_t n) {
    size_t i = 0;
    for (; i < n; ++i)
      if (!write(data[i]))
        break;
    return i;
  }
  void print(const char *s) {
    if (s)
      write((const uint8_t *)s, strlen(s));
  }
  void print(char c) { write((uint8_t)c); }
  void print(unsigned long n) {
    char s[24];
    snprintf(s, sizeof(s), "%lu", n);
    print(s);
  }
  void print(long n) {
    char s[24];
    snprintf(s, sizeof(s), "%ld", n);
    print(s);
  }
  void print(unsigned n) { print((unsigned long)n); }
  void print(int n) { print((long)n); }
  void println(const char *s = "") {
    print(s);
    write('\n');
  }
};
#endif
