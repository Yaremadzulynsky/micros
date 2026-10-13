/* Link-only fixture; never a working platform. */
#include <micros/platform.h>
#include <micros/storage.h>
#include <micros/transport.h>
#include <micros/network.h>
#include <micros/update.h>
#include <micros/telemetry.h>
void micros_platform_telemetry(micros_hardware_snapshot_t *snapshot) {}
