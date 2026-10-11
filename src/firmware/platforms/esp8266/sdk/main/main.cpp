#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "device_support.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include <micros/controller.h>
static void controller_task(void *) { micros_controller_run();vTaskDelete(NULL); }
extern "C" void app_main() {
  esp_err_t result = nvs_flash_init();
  if (result == ESP_ERR_NVS_NO_FREE_PAGES) {
    ESP_ERROR_CHECK(nvs_flash_erase());
    result = nvs_flash_init();
  }
  ESP_ERROR_CHECK(result);
  esp_log_level_set("*", ESP_LOG_ERROR);

  if (xTaskCreate(controller_task, "controller", 8192, NULL, 2, NULL) !=
      pdPASS)
    embedded_reset();
}
