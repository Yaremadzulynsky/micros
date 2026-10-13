#ifndef MICROS_INTERNAL_IPC_H
#define MICROS_INTERNAL_IPC_H

#include <micros/service.h>
#include <micros/coordination.h>

/**
 * @brief Private IPC dispatch shared by the kernel and generated SDK implementations.
 * Not part of the service authoring API; services include their generated *_ipc.h.
 * Runtime policy, ownership and generation checks remain authoritative at execution.
 */
struct micros_ipc_api {
    /** Open a configured channel key for publish or subscribe, using one owned handle. */
    micros_result_t (*ipc_open)(micros_context_t *, uint32_t channel_key, uint32_t access,
                               micros_handle_t *);
    /** Copy protobuf bytes before return; success means retained, not processed by a subscriber. */
    micros_result_t (*ipc_publish)(micros_context_t *, micros_handle_t, const uint8_t *, uint32_t);
    /**
     * Nonblocking copy into caller storage. EMPTY means no unread message. A stream
     * MISSED result advances to the oldest retained message and returns no bytes;
     * retry to receive it. CAPACITY reports required bytes without cursor advance.
     */
    micros_result_t (*ipc_read)(micros_context_t *, micros_handle_t, uint8_t *, uint32_t capacity,
                               uint32_t *message_bytes, micros_message_info_t *);
    /** Close an owned publisher/subscriber handle, including after channel recreation. */
    micros_result_t (*ipc_close)(micros_context_t *, micros_handle_t);
    micros_result_t (*coord_open)(micros_context_t *, uint32_t, uint32_t, uint32_t, micros_handle_t *);
    micros_result_t (*coord)(micros_context_t *, micros_handle_t, uint32_t,
                            uint8_t *, uint32_t, uint32_t *, micros_coord_info_t *);
};

#endif
