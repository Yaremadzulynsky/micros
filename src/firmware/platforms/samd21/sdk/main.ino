#include "device_support.h"
#include "FreeRTOS.h"
#include "hardware.h"
#include "task.h"
#include <Arduino.h>
#include <micros/controller.h>
static void controller_task(void *) { micros_controller_run();vTaskDelete(NULL); }
void setup()
{

    micros_samd21_watchdog_enable();
    if (xTaskCreate(controller_task, "controller", MICROS_CONTROLLER_TASK_STACK_BYTES / sizeof(StackType_t), NULL, 2, NULL) != pdPASS)
        micros_samd21_panic();
    vTaskStartScheduler();
    micros_samd21_panic();
}
void loop() {}
