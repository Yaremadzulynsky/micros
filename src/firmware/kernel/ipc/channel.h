#ifndef MICROS_CHANNEL_H
#define MICROS_CHANNEL_H
#include <micros/service.h>
#include <stdint.h>
/* Four channels support the v1 demo plus management/status fixtures. Eight
 * retained messages match the roadmap demo; 256-byte payloads bound copy work. */
#define MICROS_CHANNEL_CAPACITY 4u
#define MICROS_CHANNEL_MAX_DEPTH 8u
#define MICROS_CHANNEL_MAX_PAYLOAD 256u
#define MICROS_CHANNEL_POOL_BYTES                                                                  \
    (MICROS_CHANNEL_CAPACITY * MICROS_CHANNEL_MAX_DEPTH * MICROS_CHANNEL_MAX_PAYLOAD)

/**
 * @brief Fixed channel storage protected by its caller's publication lock.
 * Sequences start at one; UINT64_MAX is reserved for the exhausted cursor.
 * Generation is managed by the owner when a channel is destroyed/recreated.
 */
typedef struct {
    uint32_t key;
    uint32_t generation;
    uint32_t policy;
    uint32_t depth;
    uint32_t payload_bytes;
    uint64_t sequence;
    uint32_t lengths[MICROS_CHANNEL_MAX_DEPTH];
    uint8_t *payload; /**< depth * payload_bytes, allocated once by the runtime. */
} micros_channel_t;

micros_result_t micros_channel_publish(micros_channel_t *channel, const uint8_t *payload,
                                       uint32_t payload_bytes);
/** Stream loss advances to oldest retained and returns no payload; retry to read it.
 * Capacity failure reports required bytes without advancing. Latest reads newest. */
micros_result_t micros_channel_read(micros_channel_t *channel, uint64_t *next_sequence,
                                    uint8_t *output, uint32_t capacity, uint32_t *output_bytes,
                                    micros_message_info_t *info);
#endif
