#ifndef MICROS_COMMAND_H
#define MICROS_COMMAND_H
#include <stddef.h>
#include <stdint.h>
/* Control responses and retained diagnostics are separately bounded; package
 * payload capacity follows the MCU image envelope and fixed image slots. */
#define MICROS_MANAGEMENT_RESPONSE_BYTES 4096u
#define MICROS_MANAGEMENT_LOG_BYTES 8192u
/** @brief Privileged service-store operations; base OTA is bounded to the inactive application partition. */
typedef enum {
    MICROS_MANAGEMENT_STATUS,
    MICROS_MANAGEMENT_LOGS,
    MICROS_MANAGEMENT_IMAGE,
    MICROS_MANAGEMENT_GRAPH,
    MICROS_MANAGEMENT_ACTIVATE,
    MICROS_MANAGEMENT_STOP,
    MICROS_MANAGEMENT_REBOOT,
    MICROS_MANAGEMENT_LOG_STREAM,
    MICROS_MANAGEMENT_SESSION_BEGIN,
    MICROS_MANAGEMENT_SESSION_END,
    MICROS_MANAGEMENT_PAUSE,
    MICROS_MANAGEMENT_WIFI_GET,
    MICROS_MANAGEMENT_WIFI_SET,
    MICROS_MANAGEMENT_BASE_BEGIN,
    MICROS_MANAGEMENT_BASE_CHUNK,
    MICROS_MANAGEMENT_BASE_FINISH,
    MICROS_MANAGEMENT_BASE_CONFIRM,
    MICROS_MANAGEMENT_BASE_ABORT,
    MICROS_MANAGEMENT_PLATFORM_COMMAND,
    MICROS_MANAGEMENT_IMAGE_BEGIN,
    MICROS_MANAGEMENT_IMAGE_CHUNK,
    MICROS_MANAGEMENT_IMAGE_FINISH,
    MICROS_MANAGEMENT_GRAPH_BEGIN,
    MICROS_MANAGEMENT_GRAPH_CHUNK,
    MICROS_MANAGEMENT_GRAPH_FINISH,
    MICROS_MANAGEMENT_BASE_FETCH,
    MICROS_MANAGEMENT_RELAY_SET,
    MICROS_MANAGEMENT_BASE_ROLLBACK,
    MICROS_MANAGEMENT_BOOTLOADER,
    MICROS_MANAGEMENT_ROLLBACK
} micros_management_operation_t;
/** @brief One authenticated bounded request, owned until the serial controller replies. */
typedef struct {
    micros_management_operation_t operation;
    unsigned bank, slot;
    const uint8_t *body;
    size_t body_bytes;
    char *response;
    size_t response_capacity;
    int result;
    int physical; /* Set only by the local console transport, never by a client field. */
    uint64_t log_cursor;
    char session[33]; /* 128-bit client nonce as 32 hexadecimal characters and NUL. */
} micros_management_request_t;
/** Base controller callback; invoked only by poll on the single management task. */
typedef void (*micros_management_handler_t)(micros_management_request_t *request);
#endif
