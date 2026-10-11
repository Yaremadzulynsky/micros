#ifndef MICROS_DEVICE_GRAPH_H
#define MICROS_DEVICE_GRAPH_H
#define MICROS_DEPLOYMENT_SERVICE_SLOTS 4u
#include <stddef.h>
#include <stdint.h>
/* MRG2 identifies this fixed-width, little-endian development graph record.
 * All unused entries are zero; CRC covers every byte before checksum. */
#define MICROS_GRAPH_MAGIC UINT32_C(0x3247524d)
#define MICROS_GRAPH_VERSION 1u
#define MICROS_GRAPH_CHANNELS 4u
#define MICROS_GRAPH_BANKS 2u /* Active and staged/previous graphs use separate image files. */
/** @brief One admitted bounded channel in a persistent device graph. */
typedef struct {
    uint32_t key, policy, depth, payload_bytes;
} micros_graph_channel_t;
/** @brief One slot's manifest-derived budgets and allowed resource masks. */
typedef struct {
    uint32_t slot, handles, timers, gpio_mask, publish_mask, subscribe_mask;
    uint32_t arena_bytes, arena_alignment, stack_bytes;
} micros_graph_service_t;
/* Same 256-byte per-service limit as runtime storage; four records remain bounded. */
#define MICROS_GRAPH_CONFIG_BYTES 256u
/** @brief Persisted startup payload for the service at the same graph index. */
typedef struct {
    uint32_t bytes;
    uint8_t data[MICROS_GRAPH_CONFIG_BYTES];
} micros_graph_config_t;
/** @brief One physical GPIO binding persisted with the application.
 * Four named bindings fit the runtime's existing four-line resource budget.
 * 36 bytes hold a 32-character name, NUL and zero alignment padding. */
typedef struct {
    uint32_t pin, output;
    char name[36];
} micros_graph_gpio_t;
/** @brief Complete bounded device selection; contains no pointers or native-size fields. */
typedef struct {
    uint32_t magic, version, bank, service_count, channel_count;
    micros_graph_channel_t channels[MICROS_GRAPH_CHANNELS];
    micros_graph_service_t services[MICROS_DEPLOYMENT_SERVICE_SLOTS];
    micros_graph_config_t configurations[MICROS_DEPLOYMENT_SERVICE_SLOTS];
    uint32_t gpio_count, recovery_line;
    micros_graph_gpio_t gpio[4];
    uint32_t checksum;
} micros_device_graph_t;
#ifdef __cplusplus
static_assert(sizeof(micros_device_graph_t) == 1456,
               "five words + four channels + four services + four 260-byte configurations + GPIO count/recovery line + four 44-byte bindings + CRC");
#else
_Static_assert(sizeof(micros_device_graph_t) == 1456,
               "five words + four channels + four services + four 260-byte configurations + GPIO count/recovery line + four 44-byte bindings + CRC");
#endif
#ifdef __cplusplus
extern "C" {
#endif
/* Implemented by the shared deployment controller, not a platform backend. */
int micros_deployment_hash(unsigned bank, uint8_t hash[32]);
#ifdef __cplusplus
}
#endif
#endif
