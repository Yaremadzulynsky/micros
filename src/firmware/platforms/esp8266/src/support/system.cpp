#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "storage.h"
#include "device_support.h"

#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp_heap_caps.h"
#include "esp_ota_ops.h"
#include "esp_system.h"
#include "nvs.h"
#include "nvs_flash.h"
class SerialPort : public MicrosPrint {
public:
  using MicrosPrint::write;
  size_t write(uint8_t c) override;
  int available();
  int read();
  void flush();
  void begin();
};
static unsigned pins[4] = {2, 4, 5, 16}, outputs[4];
static uint8_t logs[1024];
static unsigned log_head, log_used;
static size_t initial_heap;
SerialPort Serial;
void SerialPort::begin() {
  uart_driver_install(UART_NUM_0, 2048, 0, 0, NULL, 0);
  uart_set_baudrate(UART_NUM_0, 115200);
  initial_heap = esp_get_free_heap_size();
}
size_t SerialPort::write(uint8_t c) {
  return uart_write_bytes(UART_NUM_0, (const char *)&c, 1) == 1 ? 1 : 0;
}
int SerialPort::available() {
  size_t n = 0;
  uart_get_buffered_data_len(UART_NUM_0, &n);
  return n;
}
int SerialPort::read() {
  uint8_t c;
  return uart_read_bytes(UART_NUM_0, &c, 1, 0) == 1 ? c : -1;
}
void SerialPort::flush() { uart_wait_tx_done(UART_NUM_0, pdMS_TO_TICKS(1000)); }
void embedded_gpio_bind(uint32_t line, uint32_t pin, uint32_t output) {
  if (line >= 4 || pin > 16 || (pin >= 6 && pin <= 11) || pin == 1 || pin == 3)
    return;
  pins[line] = pin;
  outputs[line] = output;
  gpio_config_t config = {};
  config.pin_bit_mask = 1u << pin;
  config.mode = output ? GPIO_MODE_OUTPUT : GPIO_MODE_INPUT;
  config.pull_up_en = output ? GPIO_PULLUP_DISABLE : GPIO_PULLUP_ENABLE;
  gpio_config(&config);
}
uint32_t embedded_gpio_read(uint32_t line) {
  return line < 4 ? gpio_get_level((gpio_num_t)pins[line]) : 0;
}
int embedded_gpio_write(uint32_t line, uint32_t level) {
  return line < 4 && outputs[line] && level <= 1 &&
         gpio_set_level((gpio_num_t)pins[line], level) == ESP_OK;
}
void embedded_log(const uint8_t *data, size_t bytes) {
  taskENTER_CRITICAL();
  for (size_t i = 0; i < bytes; ++i) {
    logs[(log_head + log_used) % sizeof(logs)] = data[i];
    if (log_used < sizeof(logs))
      ++log_used;
    else
      log_head = (log_head + 1) % sizeof(logs);
  }
  taskEXIT_CRITICAL();
}
size_t embedded_logs(uint8_t *data, size_t capacity) {
  taskENTER_CRITICAL();
  size_t n = log_used < capacity ? log_used : capacity;
  for (size_t i = 0; i < n; ++i)
    data[i] = logs[(log_head + i) % sizeof(logs)];
  log_head = (log_head + n) % sizeof(logs);
  log_used -= n;
  taskEXIT_CRITICAL();
  return n;
}
size_t embedded_heap_free() { return esp_get_free_heap_size(); }
size_t embedded_heap_headroom() { return esp_get_free_heap_size(); }
uint32_t embedded_heap_total() { return initial_heap; }
unsigned embedded_reset_cause() { return esp_reset_reason(); }
void embedded_reset() {
  // The ROM/second-stage loader starts with an 80 MHz clock assumption.
  esp_set_cpu_freq(ESP_CPU_FREQ_80M);
  esp_restart();
}
void embedded_idle() {}
void embedded_bootloader() {
  Serial.flush();
  esp_restart();
}
static nvs_handle journal() {
  nvs_handle handle = 0;
  const char *name = esp_ota_get_running_partition()->address >= 0x100000
                         ? "micros_graph1"
                         : "micros_graph0";
  if (nvs_open(name, NVS_READWRITE, &handle) != ESP_OK)
    return 0;
  return handle;
}
void embedded_journal_read(micros_activation_record_t records[2]) {
  memset(records, 255, 2 * sizeof(records[0]));
  nvs_handle h = journal();
  if (!h)
    return;
  for (unsigned i = 0; i < 2; ++i) {
    size_t n = sizeof(records[0]);
    if (nvs_get_blob(h, i ? "j1" : "j0", records + i, &n) != ESP_OK ||
        n != sizeof(records[0]))
      memset(records + i, 255, sizeof(records[0]));
  }
  nvs_close(h);
}
bool embedded_journal_write(unsigned sector,
                            const micros_activation_record_t &record) {
  nvs_handle h = journal();
  if (!h)
    return false;
  bool ok = nvs_set_blob(h, sector ? "j1" : "j0", &record, sizeof(record)) ==
                ESP_OK &&
            nvs_commit(h) == ESP_OK;
  nvs_close(h);
  return ok;
}

void embedded_console_begin() { Serial.begin(); }
MicrosPrint &embedded_console() { return Serial; }
int embedded_console_available() { return Serial.available(); }
int embedded_console_read() { return Serial.read(); }
void embedded_console_flush() { Serial.flush(); }
void embedded_controller_wait() { vTaskDelay(pdMS_TO_TICKS(1)); }
size_t embedded_controller_stack_free() { return uxTaskGetStackHighWaterMark(NULL) * sizeof(StackType_t); }
uint32_t embedded_target_profile() { return embedded_profile; }

extern "C" void platform_journal_read(micros_activation_record_t records[2]) { embedded_journal_read(records); }
extern "C" int platform_journal_write(unsigned sector,const micros_activation_record_t *record) { return embedded_journal_write(sector,*record); }
