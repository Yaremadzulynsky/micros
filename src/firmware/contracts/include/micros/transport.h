#ifndef MICROS_MANAGEMENT_H
#define MICROS_MANAGEMENT_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#include <micros/command.h>
/** Start Wi-Fi and the TLS management service using physically provisioned credentials. */
void micros_management_start(micros_management_handler_t handler);
/** Process at most one pending request from the base controller task. */
void micros_management_poll(void);
int micros_controller_read(uint8_t *output, size_t bytes, unsigned timeout_ms);
size_t micros_transport_write(const void *data, size_t bytes);
void micros_transport_flush(void);
/** Copy recent diagnostic bytes; zero means no retained diagnostics. */
size_t micros_transport_read_log(uint8_t *output, size_t capacity);
/** Submit a validated authenticated operation from a transport worker; returns HTTP status. */
int micros_management_execute(micros_management_request_t *request);
/** Append service diagnostics to the bounded volatile ring; safe from multiple workers. */
void micros_management_log(const uint8_t *message, size_t bytes);
#ifdef __cplusplus
}
#endif
#endif
