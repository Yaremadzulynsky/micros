#ifndef TEST_OTA_OPS_H
#define TEST_OTA_OPS_H
#include <stdint.h>
#include <stddef.h>
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_OTA_IMG_PENDING_VERIFY 1
#define ESP_PARTITION_SUBTYPE_APP_OTA_0 16
#define ESP_PARTITION_SUBTYPE_APP_OTA_1 17
#define OTA_WITH_SEQUENTIAL_WRITES ((size_t)-2)
typedef unsigned esp_ota_handle_t;
typedef unsigned esp_ota_img_states_t;
typedef struct { unsigned subtype; size_t size; } esp_partition_t;
const esp_partition_t *esp_ota_get_running_partition(void);
const esp_partition_t *esp_ota_get_next_update_partition(const esp_partition_t *p);
int esp_ota_get_state_partition(const esp_partition_t *p, esp_ota_img_states_t *s);
int esp_ota_begin(const esp_partition_t *p,size_t n,esp_ota_handle_t *h);
int esp_ota_write(esp_ota_handle_t h,const void *d,size_t n);
int esp_ota_end(esp_ota_handle_t h);
int esp_ota_abort(esp_ota_handle_t h);
int esp_ota_set_boot_partition(const esp_partition_t *p);
int esp_ota_mark_app_valid_cancel_rollback(void);
#endif
