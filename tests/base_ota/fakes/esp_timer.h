#include <stdint.h>
typedef void *esp_timer_handle_t;
typedef struct { void (*callback)(void *); const char *name; } esp_timer_create_args_t;
int esp_timer_create(const esp_timer_create_args_t *a,esp_timer_handle_t *t);
int esp_timer_start_once(esp_timer_handle_t t,uint64_t us);
int esp_timer_stop(esp_timer_handle_t t);
int esp_timer_delete(esp_timer_handle_t t);
