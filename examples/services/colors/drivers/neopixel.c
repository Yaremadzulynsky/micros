#include "neopixel.h"
#include "../generated/colors_resources.h"
/* The base configures pin mux/direction from the deployment graph. Only the
 * granted data pin's atomic output bit is touched during the timed waveform.
 * GPIO32/33 use ESP32's second output register bank. */
#define DATA_PIN COLORS_NEOPIXEL_DATA_GPIO_PIN
#define GPIO_BASE UINT32_C(0x3ff44000)
#define GPIO_OUT_SET (GPIO_BASE + (DATA_PIN < 32 ? 0x08u : 0x14u))
#define GPIO_OUT_CLEAR (GPIO_BASE + (DATA_PIN < 32 ? 0x0cu : 0x18u))
#define DATA_MASK (UINT32_C(1) << (DATA_PIN % 32))
/* This OTA driver targets the already-flashed 160 MHz base with dynamic frequency
 * scaling disabled. WS2812B uses 800 kbit/s, GRB order: 0.4/0.8 us high, 1.25 us/bit.
 * A 300 us low reset also covers newer pixels requiring more than the original 50 us. */
#define CYCLES_PER_US 160u
#define ZERO_HIGH_CYCLES (CYCLES_PER_US * 4u / 10u)
#define ONE_HIGH_CYCLES (CYCLES_PER_US * 8u / 10u)
#define BIT_CYCLES (CYCLES_PER_US * 5u / 4u)
#define RESET_CYCLES (CYCLES_PER_US * 300u)
#define POWER_SETTLE_CYCLES (CYCLES_PER_US * 1000u) /* Regulator/pixel power-up settling. */
#define PIXEL_BITS 24u /* Three eight-bit color channels, most-significant bit first. */
static volatile uint32_t *reg(uint32_t address)
{
    return (volatile uint32_t *)(uintptr_t)address;
}
static inline __attribute__((always_inline)) uint32_t cycle_count(void)
{
    uint32_t cycles;
    __asm__ volatile("rsr.ccount %0" : "=a"(cycles));
    return cycles;
}
static void wait_cycles(uint32_t cycles)
{
    uint32_t beginning = cycle_count();
    while ((uint32_t)(cycle_count() - beginning) < cycles) {
    }
}
void neopixel_show(uint8_t red, uint8_t green, uint8_t blue)
{
    uint32_t color = ((uint32_t)green << 16) | ((uint32_t)red << 8) | blue;
    *reg(GPIO_OUT_CLEAR) = DATA_MASK;
    wait_cycles(RESET_CYCLES);
    uint32_t saved_processor_status;
    /* All code/literals live in the independently loaded IRAM slot. Only the
     * 24-bit (~30 us) waveform masks interrupts on this worker's core. Restore
     * the exact previous PS; Wi-Fi continues on the other core. */
    __asm__ volatile("rsil %0, 5" : "=a"(saved_processor_status)::"memory");
    uint32_t beginning = cycle_count() - BIT_CYCLES;
    for (uint32_t mask = UINT32_C(1) << (PIXEL_BITS - 1); mask; mask >>= 1) {
        uint32_t high_cycles = color & mask ? ONE_HIGH_CYCLES : ZERO_HIGH_CYCLES;
        uint32_t now;
        do {
            now = cycle_count();
        } while ((uint32_t)(now - beginning) < BIT_CYCLES);
        *reg(GPIO_OUT_SET) = DATA_MASK;
        beginning = now;
        while ((uint32_t)(cycle_count() - beginning) < high_cycles) {
        }
        *reg(GPIO_OUT_CLEAR) = DATA_MASK;
    }
    __asm__ volatile("memw\nwsr.ps %0\nrsync" ::"a"(saved_processor_status) : "memory");
    wait_cycles(RESET_CYCLES);
}
micros_result_t neopixel_open(const micros_service_args_t *args, neopixel_t *pixel)
{
    micros_result_t result = colors_neopixel_data_open(args, &pixel->data_handle);
    if (result) return result;
    result = colors_neopixel_power_open(args, &pixel->power_handle);
    if (result) {
        args->api->gpio_close(args->context, pixel->data_handle);
        return result;
    }
    result = args->api->gpio_write(args->context, pixel->power_handle, 1);
    if (result) {
        args->api->gpio_close(args->context, pixel->power_handle);
        args->api->gpio_close(args->context, pixel->data_handle);
        return result;
    }
    pixel->acquired = true;
    wait_cycles(POWER_SETTLE_CYCLES);
    return MICROS_OK;
}
void neopixel_close(const micros_service_args_t *args, neopixel_t *pixel)
{
    if (!pixel->acquired) return;
    neopixel_show(0,0,0);
    args->api->gpio_close(args->context,pixel->power_handle);
    args->api->gpio_close(args->context,pixel->data_handle);
    pixel->acquired=false;
}
