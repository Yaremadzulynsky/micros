#include <micros/telemetry.h>
void micros_platform_telemetry(micros_hardware_snapshot_t *snapshot) {
 *snapshot=(micros_hardware_snapshot_t){.profile="posix",.recovery_pin=-1};
}
