#include <Arduino.h>
#include "hardware.h"
// Override Arduino's erase-first reset path: entering USB recovery must never
// erase either base slot or the selector. The stock bootloader consumes this marker.
static volatile int reset_ticks=-1;
extern "C" void initiateReset(int ticks) {reset_ticks=ticks;}
extern "C" void cancelReset(void) {reset_ticks=-1;}
extern "C" void tickReset(void) {
    if(reset_ticks<0 || --reset_ticks>0)return;
    __disable_irq();micros_samd21_watchdog_disable();
    *(volatile uint32_t *)0x20007ffc=0x07738135;
    NVIC_SystemReset();
}
