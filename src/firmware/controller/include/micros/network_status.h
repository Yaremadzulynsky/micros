#ifndef MICROS_NETWORK_STATUS_H
#define MICROS_NETWORK_STATUS_H
#include <micros/network.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Existing compact protocol schema. Returns zero on overflow. */
size_t micros_network_status_json(char *output, size_t capacity,
                                  const micros_network_snapshot_t *snapshot);
#ifdef __cplusplus
}
#endif
#endif
