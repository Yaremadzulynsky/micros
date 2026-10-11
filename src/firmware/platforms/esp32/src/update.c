/* Controller-owned OTA: existing transport buffers feed sequential flash writes.
 * No additional worker, network stack, filesystem, or full-image allocation. */
#include <micros/update.h>
#include "sdkconfig.h"
#include <stdio.h>
#if CONFIG_MICROS_BASE_OTA
#include "esp_ota_ops.h"
#include "esp_timer.h"
#include "esp_system.h"
#include "esp_app_desc.h"
#include "nvs.h"
#include "mbedtls/sha256.h"
#include <string.h>
const uint32_t micros_base_ota_version = 1;
static esp_ota_handle_t upload;
static const esp_partition_t *target;
static uint32_t base_bytes, received;
static uint8_t expected[32];
static mbedtls_sha256_context hash;
static int active, sealed, pending;
static esp_timer_handle_t trial_timer;
static unsigned running_slot(void)
{
    return esp_ota_get_running_partition()->subtype == ESP_PARTITION_SUBTYPE_APP_OTA_1;
}
static void trial_expired(void *unused)
{
    (void)unused;
    /* Bootloader rolls back any still-unconfirmed image on reset. */
    esp_restart();
}
void micros_base_boot(void)
{
    esp_ota_img_states_t state;
    pending = esp_ota_get_state_partition(esp_ota_get_running_partition(), &state) == ESP_OK &&
              state == ESP_OTA_IMG_PENDING_VERIFY;
    if (pending) {
        esp_timer_create_args_t args = {.callback = trial_expired, .name = "base-trial"};
        if (esp_timer_create(&args, &trial_timer) != ESP_OK ||
            esp_timer_start_once(trial_timer, UINT64_C(1000000) * MICROS_BASE_TRIAL_SECONDS) != ESP_OK)
            esp_restart();
    }
}
/* Bind shared application storage to the base that admitted it. A new base
 * leaves old packages inert, including across reboots after confirmation. */
int micros_base_application_allowed(const uint8_t graph_hash[32])
{
    nvs_handle_t handle;
    if (nvs_open("micros_base", NVS_READONLY, &handle) != ESP_OK) return 0;
    uint8_t owner[64];
    int okay = 0;
    for (unsigned bank = 0; bank < 2; ++bank) {
        size_t bytes = sizeof(owner);
        if (nvs_get_blob(handle, bank ? "owner1" : "owner0", owner, &bytes) == ESP_OK &&
            bytes == sizeof(owner) &&
            !memcmp(owner, esp_app_get_description()->app_elf_sha256, 32) &&
            !memcmp(owner + 32, graph_hash, 32)) okay = 1;
    }
    nvs_close(handle);
    return okay && !pending;
}
int micros_base_bind_application(unsigned bank, const uint8_t graph_hash[32])
{
    if (pending || bank > 1) return 0;
    nvs_handle_t handle;
    if (nvs_open("micros_base", NVS_READWRITE, &handle) != ESP_OK) return 0;
    uint8_t owner[64];
    memcpy(owner, esp_app_get_description()->app_elf_sha256, 32);
    memcpy(owner + 32, graph_hash, 32);
    int okay = nvs_set_blob(handle, bank ? "owner1" : "owner0", owner, sizeof(owner)) == ESP_OK &&
               nvs_commit(handle) == ESP_OK;
    nvs_close(handle);
    return okay;
}
int micros_base_pending(void) { return pending; }
int micros_base_busy(void) { return active || sealed; }
void micros_base_abort(void)
{
    if (active) {
        if (upload) esp_ota_abort(upload);
        mbedtls_sha256_free(&hash);
    }
    upload = 0;
    active = 0;
    /* A sealed image has already changed boot selection. It must reboot; a
     * session close must not permit starting another upload before reboot. */
}
int micros_base_begin(const uint8_t *header, size_t bytes)
{
    if (pending || active || sealed || bytes != MICROS_BASE_HEADER_BYTES || memcmp(header, "MBO1", 4))
        return 0;
    memcpy(&base_bytes, header + 4, 4);
    target = esp_ota_get_next_update_partition(NULL);
    unsigned next = 1 - running_slot();
    if (!target || target->subtype != ESP_PARTITION_SUBTYPE_APP_OTA_0 + next ||
        base_bytes < 288 || base_bytes > target->size)
        return 0;
    if (esp_ota_begin(target, OTA_WITH_SEQUENTIAL_WRITES, &upload) != ESP_OK)
        return 0;
    memcpy(expected, header + 8, 32);
    received = 0;
    mbedtls_sha256_init(&hash);
    active = 1;
    if (mbedtls_sha256_starts(&hash, 0)) {
        micros_base_abort();
        return 0;
    }
    return 1;
}
int micros_base_chunk(uint64_t offset, const uint8_t *data, size_t bytes)
{
    if (!active || !bytes || bytes > MICROS_BASE_CHUNK_BYTES || offset != received ||
        bytes > base_bytes - received)
        return 0;
    int okay = esp_ota_write(upload, data, bytes) == ESP_OK;
    if (okay) okay = mbedtls_sha256_update(&hash, data, bytes) == 0;
    if (!okay) {
        micros_base_abort();
        return 0;
    }
    received += bytes;
    return 1;
}
int micros_base_finish(void)
{
    if (!active || received != base_bytes) return 0;
    uint8_t actual[32];
    int okay = !mbedtls_sha256_finish(&hash, actual) && !memcmp(actual, expected, 32);
    if (!okay) { micros_base_abort(); return 0; }
    esp_err_t result = esp_ota_end(upload); /* Frees handle even on validation error. */
    upload = 0;
    if (result != ESP_OK) { micros_base_abort(); return 0; }
    okay = esp_ota_set_boot_partition(target) == ESP_OK;
    micros_base_abort();
    sealed = okay;
    return okay;
}
int micros_base_confirm(void)
{
    if (!pending) return 1; /* Idempotent after a lost confirmation response. */
    if (esp_ota_mark_app_valid_cancel_rollback() != ESP_OK) return 0;
    pending = 0;
    esp_timer_stop(trial_timer);
    esp_timer_delete(trial_timer);
    trial_timer = NULL;
    return 1;
}
size_t micros_base_status(char *output, size_t capacity)
{
    const esp_partition_t *next = esp_ota_get_next_update_partition(NULL);
    int bytes = snprintf(output, capacity,
        "{\"version\":1,\"slot\":%u,\"slot_bytes\":%lu,\"pending\":%s,\"uploading\":%s,"
        "\"received\":%lu,\"chunk_bytes\":%u,\"trial_seconds\":%u}", running_slot(),
        (unsigned long)(next ? next->size : 0), pending ? "true" : "false",
        active ? "true" : "false", (unsigned long)received,
        MICROS_BASE_CHUNK_BYTES, MICROS_BASE_TRIAL_SECONDS);
    return bytes < 0 || (size_t)bytes >= capacity ? 0 : (size_t)bytes;
}
#else
void micros_base_boot(void) {}
int micros_base_application_allowed(const uint8_t graph_hash[32]) { (void)graph_hash; return 1; }
int micros_base_bind_application(unsigned bank, const uint8_t graph_hash[32]) { (void)bank; (void)graph_hash; return 1; }
int micros_base_pending(void) { return 0; }
int micros_base_busy(void) { return 0; }
void micros_base_abort(void) {}
int micros_base_begin(const uint8_t *h, size_t n) { (void)h; (void)n; return 0; }
int micros_base_chunk(uint64_t o, const uint8_t *d, size_t n) { (void)o; (void)d; (void)n; return 0; }
int micros_base_finish(void) { return 0; }
int micros_base_confirm(void) { return 0; }
size_t micros_base_status(char *o, size_t n) {
    int bytes = snprintf(o, n, "{\"version\":0}");
    return bytes < 0 || (size_t)bytes >= n ? 0 : (size_t)bytes;
}
#endif

int micros_base_rollback(void) { return 0; }
