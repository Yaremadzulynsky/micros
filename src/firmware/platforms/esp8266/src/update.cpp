#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "support/storage.h"
#include "device_support.h"
#include "../sdk/boot/record.h"
#include "esp_ota_ops.h"
#include "esp_spi_flash.h"
#include "esp_timer.h"
extern "C" {
#include "sha256.h"
}
static unsigned staging = MICROS_BOOT_NONE, image_bytes, written;
static esp_ota_handle_t handle;
static uint8_t expected[32];
static unsigned running_slot() {
  return esp_ota_get_running_partition()->subtype -
         ESP_PARTITION_SUBTYPE_APP_OTA_0;
}
static int load(micros_boot_record_t &r) {
  micros_boot_record_t records[2];
  if (spi_flash_read(MICROS_BOOT_ADDRESS, records, sizeof(r)) != ESP_OK ||
      spi_flash_read(MICROS_BOOT_ADDRESS + 4096, records + 1, sizeof(r)) !=
          ESP_OK)
    return -1;
  int i = micros_boot_latest(records);
  if (i >= 0)
    r = records[i];
  return i;
}
static bool store(micros_boot_record_t r, int old) {
  if (!micros_boot_seal(&r))
    return false;
  uint32_t address = MICROS_BOOT_ADDRESS + (old == 0 ? 4096 : 0);
  if (spi_flash_erase_sector(address / 4096) != ESP_OK ||
      spi_flash_write(address, &r, sizeof(r)) != ESP_OK)
    return false;
  micros_boot_record_t check;
  return spi_flash_read(address, &check, sizeof(check)) == ESP_OK &&
         micros_boot_valid(&check) && check.sequence == r.sequence;
}
static const esp_partition_t *partition(unsigned slot) {
  return slot < 2
             ? esp_partition_find_first(
                   ESP_PARTITION_TYPE_APP,
                   (esp_partition_subtype_t)(ESP_PARTITION_SUBTYPE_APP_OTA_0 +
                                             slot),
                   NULL)
             : NULL;
}
unsigned embedded_base_ota_size() { return staging < 2 ? image_bytes : 0; }
void embedded_base_ota_status(MicrosPrint &out) {
  micros_boot_record_t r;
  int i = load(r);
  out.print("{\"version\":");
  out.print(i < 0 ? 0 : 1);
  out.print(",\"slot\":");
  out.print(running_slot());
  out.print(",\"slot_bytes\":");
  out.print(MICROS_BASE_BYTES);
  out.print(",\"good\":");
  out.print(i < 0 ? MICROS_BOOT_NONE : r.good);
  out.print(",\"previous\":");
  out.print(i < 0 ? MICROS_BOOT_NONE : r.previous);
  out.print(",\"candidate\":");
  out.print(i < 0 ? MICROS_BOOT_NONE : r.candidate);
  out.print(",\"pending\":");
  out.print(i >= 0 && r.candidate < 2 ? 1 : 0);
  out.print(",\"staging\":");
  out.print(staging);
  out.print(",\"written\":");
  out.print(written);
  out.print('}');
}
void embedded_base_ota_abort() {
  if (handle)
    esp_ota_end(handle); // SDK 3.4 has no abort; end releases state even on
                         // incomplete images.
  handle = 0;
  staging = MICROS_BOOT_NONE;
  written = 0;
}
bool embedded_base_ota_begin(unsigned slot, unsigned bytes,
                             const uint8_t *hash) {
  micros_boot_record_t r;
  int i = load(r);
  if (i < 0 || slot > 1 || slot == running_slot() || r.good != running_slot() ||
      r.candidate < 2 || staging < 2 || bytes < 256 ||
      bytes > MICROS_BASE_BYTES || (bytes & 3))
    return false;
  r.previous = MICROS_BOOT_NONE;
  if (!store(r, i))
    return false;
  if (esp_ota_begin(partition(slot), bytes, &handle) != ESP_OK) {
    handle = 0;
    return false;
  }
  staging = slot;
  image_bytes = bytes;
  written = 0;
  memcpy(expected, hash, 32);
  return true;
}
bool embedded_base_ota_write(unsigned offset, const uint8_t *data,
                             unsigned bytes) {
  if (staging > 1 || !handle || offset > written || !bytes || bytes > 256 ||
      (bytes % 64) || offset >= image_bytes)
    return false;
  unsigned count = image_bytes - offset;
  if (count > bytes)
    count = bytes;
  if (offset < written) {
    uint8_t previous[256];
    return count <= written - offset &&
           esp_partition_read(partition(staging), offset, previous, count) ==
               ESP_OK &&
           !memcmp(previous, data, count);
  }
  if (esp_ota_write(handle, data, count) != ESP_OK)
    return false;
  written += count;
  return true;
}
bool embedded_base_ota_activate() {
  if (staging > 1 || !handle || written != image_bytes)
    return false;
  micros_sha256_t state;
  micros_sha256_init(&state);
  uint8_t bytes[256], hash[32];
  for (unsigned offset = 0; offset < image_bytes; offset += sizeof(bytes)) {
    unsigned n = image_bytes - offset;
    if (n > sizeof(bytes))
      n = sizeof(bytes);
    if (esp_partition_read(partition(staging), offset, bytes, n) != ESP_OK)
      return false;
    micros_sha256_update(&state, bytes, n);
    vTaskDelay(1);
  }
  micros_sha256_finish(&state, hash);
  if (memcmp(hash, expected, 32))
    return false;
  esp_err_t result = esp_ota_end(handle);
  handle = 0;
  if (result != ESP_OK)
    return false;
  micros_boot_record_t r;
  int i = load(r);
  if (i < 0 || r.good != running_slot() || r.candidate < 2)
    return false;
  r.candidate = staging;
  r.attempts = 0;
  if (!store(r, i))
    return false;
  staging = MICROS_BOOT_NONE;
  written = 0;
  return true;
}
bool embedded_base_ota_rollback() {
  micros_boot_record_t r;
  int i = load(r);
  if (i < 0 || r.good != running_slot() || r.candidate < 2 || r.previous > 1 ||
      staging < 2)
    return false;
  r.candidate = r.previous;
  r.previous = MICROS_BOOT_NONE;
  r.attempts = 0;
  return store(r, i);
}
void embedded_base_ota_poll() {
  static bool done = false;
  if (done)
    return;
  // Flash reads briefly mask interrupts on this chip. Polling the journal on
  // every 1 ms management tick can interfere with TLS/Wi-Fi during a trial.
  static uint64_t next_check;
  uint64_t now = esp_timer_get_time();
  if (now < next_check)
    return;
  next_check = now + 100000;
  micros_boot_record_t r;
  int i = load(r);
  if (i < 0) {
    done = true;
    return;
  }
  if (r.candidate != running_slot()) {
    if (r.candidate < 2 && r.good == running_slot() && r.attempts) {
      r.candidate = MICROS_BOOT_NONE;
      r.attempts = 0;
      if (!store(r, i))
        return;
    }
    done = true;
    return;
  }
  if (now >= 10000000 && embedded_network_online()) {
    r.previous = r.good;
    r.good = r.candidate;
    r.candidate = MICROS_BOOT_NONE;
    r.attempts = 0;
    if (store(r, i))
      done = true;
  } else if (now >= 180000000)
    embedded_reset();
}

#include <micros/update.h>
#include "support/buffer_print.h"
extern "C" void micros_base_boot(void) { embedded_base_ota_poll(); }
extern "C" int micros_base_application_allowed(const uint8_t hash[32]) { (void)hash;return 1; }
extern "C" int micros_base_bind_application(unsigned bank,const uint8_t hash[32]) { (void)hash;return bank<2; }
extern "C" int micros_base_busy(void) { return staging<2; }
extern "C" void micros_base_abort(void) { embedded_base_ota_abort(); }
extern "C" int micros_base_begin(const uint8_t *header,size_t bytes) {
 if(bytes!=40 || !header || memcmp(header,"MBO1",4))return 0;
 uint32_t length;memcpy(&length,header+4,4);
 return embedded_base_ota_begin(1-running_slot(),length,header+8);
}
extern "C" int micros_base_chunk(uint64_t offset,const uint8_t *data,size_t bytes) {
 return offset<=UINT32_MAX && bytes<=UINT32_MAX && embedded_base_ota_write((unsigned)offset,data,(unsigned)bytes);
}
extern "C" int micros_base_finish(void) { return embedded_base_ota_activate(); }
extern "C" size_t micros_base_status(char *out,size_t capacity) {
 MicrosBufferPrint writer(out,capacity);embedded_base_ota_status(writer);return writer.size();
}

extern "C" int micros_base_pending(void) { micros_boot_record_t record;return load(record)>=0 && record.candidate<2; }
extern "C" int micros_base_confirm(void) { micros_boot_record_t record;int sector=load(record);
 if(sector<0)return 0;
 if(record.candidate!=running_slot())return record.good==running_slot();
 record.previous=record.good;record.good=record.candidate;record.candidate=MICROS_BOOT_NONE;record.attempts=0;
 return store(record,sector); }

extern "C" int micros_base_rollback(void) { return embedded_base_ota_rollback(); }
