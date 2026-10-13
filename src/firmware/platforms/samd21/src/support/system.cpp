#include "storage.h"
#include "device_support.h"
#include "hardware.h"
#include "FreeRTOS.h"
#include "task.h"
#include <Arduino.h>
#include <errno.h>
#include <malloc.h>
#include <reent.h>

static volatile uint64_t elapsed_ms;
extern "C" void micros_samd21_watchdog_enable(void)
{
    // Dedicated 1 kHz clock; the watchdog also recovers faults with IRQs disabled.
    GCLK->GENDIV.reg = GCLK_GENDIV_ID(4) | GCLK_GENDIV_DIV(32);
    while (GCLK->STATUS.bit.SYNCBUSY)
    {
    }
    GCLK->GENCTRL.reg = GCLK_GENCTRL_ID(4) | GCLK_GENCTRL_SRC_OSCULP32K | GCLK_GENCTRL_GENEN;
    while (GCLK->STATUS.bit.SYNCBUSY)
    {
    }
    GCLK->CLKCTRL.reg = GCLK_CLKCTRL_ID_WDT | GCLK_CLKCTRL_GEN_GCLK4 | GCLK_CLKCTRL_CLKEN;
    while (GCLK->STATUS.bit.SYNCBUSY)
    {
    }
    WDT->CTRL.reg = 0;
    while (WDT->STATUS.bit.SYNCBUSY)
    {
    }
    WDT->CONFIG.reg = WDT_CONFIG_PER_16K;
    WDT->CTRL.reg = WDT_CTRL_ENABLE;
    while (WDT->STATUS.bit.SYNCBUSY)
    {
    }
}
extern "C" void micros_samd21_watchdog_disable(void)
{
    WDT->CTRL.reg = 0;
    while (WDT->STATUS.bit.SYNCBUSY)
    {
    }
}
extern "C" void micros_samd21_watchdog_kick(void)
{
    if (!WDT->STATUS.bit.SYNCBUSY)
        WDT->CLEAR.reg = WDT_CLEAR_CLEAR_KEY;
}
static uint8_t log_ring[768];
static unsigned log_start, log_size;
static uint8_t gpio_pins[4] = {255, 255, 255, 255}, gpio_outputs[4];
extern "C" void embedded_gpio_bind(uint32_t line, uint32_t pin, uint32_t output)
{
    if (line >= 4)
        return;
    if (gpio_pins[line] != 255)
        pinMode(gpio_pins[line], INPUT);
    gpio_pins[line] = pin <= 21 ? pin : 255;
    gpio_outputs[line] = output;
    if (pin <= 21)
    {
        pinMode(pin, output ? OUTPUT : INPUT_PULLUP);
        if (output)
            digitalWrite(pin, LOW);
    }
}
extern "C" uint32_t embedded_gpio_read(uint32_t line)
{
    return line < 4 && gpio_pins[line] != 255 ? digitalRead(gpio_pins[line]) != 0 : 0;
}
extern "C" int embedded_gpio_write(uint32_t line, uint32_t level)
{
    if (line >= 4 || gpio_pins[line] == 255 || !gpio_outputs[line])
        return 0;
    digitalWrite(gpio_pins[line], level ? HIGH : LOW);
    return 1;
}
extern "C" void embedded_log(const uint8_t *data, size_t bytes)
{
    taskENTER_CRITICAL();
    for (size_t i = 0; i < bytes; ++i)
    {
        if (log_size == sizeof(log_ring))
        {
            log_start = (log_start + 1) % sizeof(log_ring);
            --log_size;
        }
        log_ring[(log_start + log_size++) % sizeof(log_ring)] = data[i];
    }
    taskEXIT_CRITICAL();
}
extern "C" size_t embedded_logs(uint8_t *data, size_t capacity)
{
    taskENTER_CRITICAL();
    size_t n = log_size < capacity ? log_size : capacity;
    for (size_t i = 0; i < n; ++i)
        data[i] = log_ring[(log_start + i) % sizeof(log_ring)];
    log_start = (log_start + n) % sizeof(log_ring);
    log_size -= n;
    taskEXIT_CRITICAL();
    return n;
}
extern "C" void micros_freertos_systick(void);
extern "C" void SysTick_DefaultHandler(void);
extern "C" int sysTickHook(void)
{
    ++elapsed_ms;
    SysTick_DefaultHandler(); // Preserve Arduino timing and 1200-baud USB reset.
    if (xTaskGetSchedulerState() != taskSCHEDULER_NOT_STARTED)
        micros_freertos_systick();
    return 1;
}
extern "C" uint64_t micros_samd21_clock_us(void)
{
    uint32_t mask = __get_PRIMASK();
    __disable_irq();
    uint64_t ms = elapsed_ms;
    uint32_t ticks = SysTick->VAL;
    if (SCB->ICSR & SCB_ICSR_PENDSTSET_Msk)
    {
        ++ms;
        ticks = SysTick->VAL;
    }
    uint64_t result = ms * 1000 + (SysTick->LOAD - ticks) / 48;
    __set_PRIMASK(mask);
    return result;
}
extern "C" void micros_samd21_led_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}
extern "C" void micros_samd21_led_write(uint32_t level)
{
    digitalWrite(LED_BUILTIN, level ? HIGH : LOW);
}
extern "C" uint32_t micros_samd21_led_read(void) { return digitalRead(LED_BUILTIN) ? 1 : 0; }
extern "C" size_t micros_samd21_serial_write(const uint8_t *bytes, size_t count)
{
    // Disconnecting diagnostics must not fail an otherwise healthy service.
    if (!Serial)
        return count;
    if (Serial.availableForWrite() < (int)count)
        return count; // Bounded, lossy diagnostics.
    return Serial.write(bytes, count);
}
extern "C" void embedded_reset(void)
{
    micros_samd21_watchdog_disable();
    NVIC_SystemReset();
}
extern "C" void micros_samd21_panic(void)
{
    micros_samd21_watchdog_disable();
    NVIC_SystemReset();
    for (;;)
    {
    }
}
extern "C" void vApplicationStackOverflowHook(TaskHandle_t, char *) { micros_samd21_panic(); }

// One libc heap serves both the kernel and FreeRTOS heap_3. Never compare the
// heap break with PSP: a task's stack itself lives inside that heap.
extern "C" uint32_t __bss_end__, __StackTop;
static char *heap_end;
extern "C" void *_sbrk(ptrdiff_t increment)
{
    if (!heap_end)
        heap_end = (char *)&__bss_end__;
    char *limit = (char *)&__StackTop - 2048; // Reserve the interrupt/main stack.
    if (increment < 0 || heap_end > limit || (size_t)increment > (size_t)(limit - heap_end))
    {
        errno = ENOMEM;
        return (void *)-1;
    }
    char *previous = heap_end;
    heap_end += increment;
    return previous;
}
extern "C" size_t embedded_heap_headroom(void)
{
    return (size_t)((char *)&__StackTop - 2048 - (heap_end ? heap_end : (char *)&__bss_end__));
}
extern "C" void __malloc_lock(struct _reent *) { vTaskSuspendAll(); }
extern "C" void __malloc_unlock(struct _reent *) { (void)xTaskResumeAll(); }

extern "C" size_t embedded_heap_free(void)
{
    return embedded_heap_headroom() + mallinfo().fordblks;
}

extern "C" uint32_t __bss_end__, __StackTop;
extern "C" void initiateReset(int ms);
uint32_t embedded_heap_total(void) { return (char *)&__StackTop - 2048 - (char *)&__bss_end__; }
unsigned embedded_reset_cause(void) { return PM->RCAUSE.reg; }
void embedded_bootloader() { micros_samd21_watchdog_disable(); initiateReset(250); }
void embedded_idle() {
  if (Serial.baud() == 1200) micros_samd21_watchdog_disable();
  else micros_samd21_watchdog_kick();
}
void embedded_journal_read(micros_activation_record_t records[2]) {
  memcpy(records, (void *)SAMD_JOURNAL_BASE, sizeof(records[0]));
  memcpy(records + 1, (void *)(SAMD_JOURNAL_BASE + 256), sizeof(records[0]));
}
bool embedded_journal_write(unsigned sector, const micros_activation_record_t &next) {
  uint32_t address = SAMD_JOURNAL_BASE + sector * 256;
  uint8_t pages[192]; memset(pages, 255, sizeof(pages)); memcpy(pages, &next, sizeof(next));
  // Commit is in the third page; interrupted writes retain the other erase row.
  if (!embedded_flash_erase(address, 256) || !embedded_flash_write(address, pages, 128) ||
      !embedded_flash_write(address + 128, pages + 128, 64)) return false;
  const micros_activation_record_t *written = (const micros_activation_record_t *)(uintptr_t)address;
  return micros_activation_valid(written) && !memcmp(written, &next, sizeof(next));
}
class Console : public MicrosPrint {
public:
  size_t write(uint8_t c) override { return Serial.write(c); }
  size_t write(const uint8_t *data, size_t bytes) override { return Serial.write(data, bytes); }
};
void embedded_console_begin() { Serial.begin(115200); }
MicrosPrint &embedded_console() { static Console console; return console; }
int embedded_console_available() { return Serial.available(); }
int embedded_console_read() { return Serial.read(); }
void embedded_console_flush() { Serial.flush(); }
void embedded_controller_wait() { vTaskDelay(pdMS_TO_TICKS(1)); }
size_t embedded_controller_stack_free() { return uxTaskGetStackHighWaterMark(NULL) * sizeof(StackType_t); }
uint32_t embedded_target_profile() { return micros_samd21_profile; }

extern "C" void platform_journal_read(micros_activation_record_t records[2]) { embedded_journal_read(records); }
extern "C" int platform_journal_write(unsigned sector,const micros_activation_record_t *record) { return embedded_journal_write(sector,*record); }
