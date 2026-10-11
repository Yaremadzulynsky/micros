#include <micros/telemetry.h>
#include "support/board_profile.h"
#include <micros/platform.h>
#include <micros/capabilities.h>
#include <micros/controller.h>
#include "driver/gpio.h"
#include "esp_heap_caps.h"
/* Called by the serialized management controller. No runtime or JSON dependency. */
void micros_platform_telemetry(micros_hardware_snapshot_t *snapshot)
{
    static micros_gpio_snapshot_t gpio[4];
    const micros_graph_gpio_t *lines;
    unsigned count = micros_board_gpio_bindings(&lines);
    for (unsigned i = 0; i < count; ++i)
        gpio[i] = (micros_gpio_snapshot_t){lines[i].name, i, (int)lines[i].pin,
                                         (int)lines[i].output, gpio_get_level(lines[i].pin)};
    *snapshot = (micros_hardware_snapshot_t){
        .profile = MICROS_BOARD_PROFILE, .flash_mb = MICROS_BOARD_FLASH_MB,
        .recovery_pin = micros_board_recovery_pin(), .gpio = gpio, .gpio_count = count,
        .internal_free = heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
        .internal_total = heap_caps_get_total_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
        .internal_min = heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
        .internal_largest = heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
        .external_total = heap_caps_get_total_size(MALLOC_CAP_SPIRAM),
        .external_free = heap_caps_get_free_size(MALLOC_CAP_SPIRAM),
    };
    snapshot->runtime_allocations_internal = !snapshot->external_total;
#if defined(CONFIG_SPIRAM_USE_CAPS_ALLOC)
    snapshot->runtime_allocations_internal = 1;
#endif
}
