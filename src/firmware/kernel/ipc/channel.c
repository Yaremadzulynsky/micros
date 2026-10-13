#include "channel.h"
#include <string.h>

micros_result_t micros_channel_publish(micros_channel_t *channel, const uint8_t *payload,
                                       uint32_t payload_bytes)
{
    if (!payload && payload_bytes)
        return MICROS_ERROR_INVALID_ARGUMENT;
    if (payload_bytes > channel->payload_bytes)
        return MICROS_ERROR_CAPACITY;
    /* Keep UINT64_MAX representable as the cursor after the last valid message.
     * Exhaustion requires channel recreation and therefore a new generation. */
    if (channel->sequence >= UINT64_MAX - 1)
        return MICROS_ERROR_CAPACITY;
    uint64_t sequence = channel->sequence + 1;
    uint32_t slot = (uint32_t)((sequence - 1) % channel->depth);
    if (payload_bytes)
        memcpy(channel->payload + (size_t)slot * channel->payload_bytes, payload, payload_bytes);
    channel->lengths[slot] = payload_bytes;
    channel->sequence = sequence;
    return MICROS_OK;
}
micros_result_t micros_channel_read(micros_channel_t *channel, uint64_t *next_sequence,
                                    uint8_t *output, uint32_t capacity, uint32_t *output_bytes,
                                    micros_message_info_t *info)
{
    if (!next_sequence || !output_bytes || !info || (!output && capacity))
        return MICROS_ERROR_INVALID_ARGUMENT;
    *output_bytes = 0;
    *info = (micros_message_info_t){0};
    if (!channel->sequence || *next_sequence > channel->sequence)
        return MICROS_ERROR_EMPTY;
    uint64_t oldest =
        channel->sequence >= channel->depth ? channel->sequence - channel->depth + 1 : 1;
    if (channel->policy == MICROS_CHANNEL_STREAM && *next_sequence < oldest) {
        info->messages_missed = oldest - *next_sequence;
        info->sequence = oldest;
        *next_sequence = oldest;
        return MICROS_ERROR_MESSAGES_MISSED;
    }
    uint64_t sequence =
        channel->policy == MICROS_CHANNEL_LATEST ? channel->sequence : *next_sequence;
    uint32_t slot = (uint32_t)((sequence - 1) % channel->depth);
    *output_bytes = channel->lengths[slot];
    info->sequence = sequence;
    if (channel->policy == MICROS_CHANNEL_LATEST)
        info->messages_missed = sequence - *next_sequence;
    if (capacity < channel->lengths[slot])
        return MICROS_ERROR_CAPACITY;
    if (channel->lengths[slot])
        memcpy(output, channel->payload + (size_t)slot * channel->payload_bytes, channel->lengths[slot]);
    *next_sequence = sequence + 1;
    return MICROS_OK;
}
