#ifndef MICROS_TELEMETRY_H
#define MICROS_TELEMETRY_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Hardware measurements only. Reporting/schema ownership belongs to management.
 * A target implementing this contract must fill a complete snapshot. */
typedef struct {
    const char *name;
    uint32_t line;
    int pin, output, level;
} micros_gpio_snapshot_t;
typedef struct {
    const char *profile;
    unsigned flash_mb;
    int recovery_pin;
    const micros_gpio_snapshot_t *gpio;
    unsigned gpio_count;
    size_t internal_free, internal_total, internal_min, internal_largest;
    size_t external_total, external_free;
    size_t controller_stack_free;
    int runtime_allocations_internal;
} micros_hardware_snapshot_t;
void micros_platform_telemetry(micros_hardware_snapshot_t *snapshot);
#ifdef __cplusplus
}
#endif
#endif
