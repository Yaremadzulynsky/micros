#ifndef MICROS_MANAGEMENT_STATUS_H
#define MICROS_MANAGEMENT_STATUS_H
#include "runtime.h"
#include <micros/telemetry.h>
/* Append status fields to an open JSON object. Capacity means overflow; callers
 * must discard that response. Network JSON is supplied by the network reporter. */
size_t micros_status_append(char *output, size_t capacity, size_t used,
                           micros_runtime_t *runtime,
                           const micros_hardware_snapshot_t *hardware,
                           size_t (*network_json)(char *, size_t));
#endif
