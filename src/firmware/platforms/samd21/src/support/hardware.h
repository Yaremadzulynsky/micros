#ifndef MICROS_SAMD21_HARDWARE_H
#define MICROS_SAMD21_HARDWARE_H
#include <stddef.h>
#include <stdint.h>
#include "device_support.h"
#ifdef __cplusplus
extern "C"
{
#endif
    uint64_t micros_samd21_clock_us(void);
    void micros_samd21_led_init(void);
    void micros_samd21_led_write(uint32_t level);
    uint32_t micros_samd21_led_read(void);
    size_t micros_samd21_serial_write(const uint8_t *bytes, size_t count);
    void micros_samd21_watchdog_enable(void);
    void micros_samd21_watchdog_disable(void);
    void micros_samd21_watchdog_kick(void);
#ifdef __cplusplus
}
#endif
#endif
