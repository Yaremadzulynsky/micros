// Hardware recovery fixture only; never selected by a normal base build.
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
extern "C" void embedded_management(void *);
extern "C" void app_main() {
  // Retain the normal controller's link layout for host image verification.
  volatile bool start = false;
  if (start)
    embedded_management(nullptr);
  taskDISABLE_INTERRUPTS();
  for (;;) {
    __asm__ __volatile__("nop");
  }
}
