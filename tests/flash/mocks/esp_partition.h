#ifndef TEST_PARTITION_H
#define TEST_PARTITION_H
#include <stddef.h>
#include <stdint.h>
typedef struct { size_t size; unsigned id; } esp_partition_t;
typedef unsigned esp_partition_mmap_handle_t;
#define ESP_OK 0
#define ESP_PARTITION_TYPE_DATA 1
#define ESP_PARTITION_SUBTYPE_ANY 0
#define ESP_PARTITION_MMAP_INST 1
#define ESP_PARTITION_MMAP_DATA 2
const esp_partition_t *esp_partition_find_first(int type, int subtype, const char *name);
int esp_partition_read(const esp_partition_t *, size_t, void *, size_t);
int esp_partition_write(const esp_partition_t *, size_t, const void *, size_t);
int esp_partition_erase_range(const esp_partition_t *, size_t, size_t);
int esp_partition_mmap(const esp_partition_t *, size_t, size_t, int, const void **, esp_partition_mmap_handle_t *);
void esp_partition_munmap(esp_partition_mmap_handle_t);
#endif
