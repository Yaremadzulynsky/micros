#include "device_support.h"
#include <micros/telemetry.h>
extern "C" void micros_platform_telemetry(micros_hardware_snapshot_t *snapshot) {
 memset(snapshot,0,sizeof(*snapshot));snapshot->profile=EMBEDDED_PLATFORM;snapshot->recovery_pin=-1;
 snapshot->internal_free=embedded_heap_free();snapshot->internal_total=embedded_heap_total();
 snapshot->internal_largest=embedded_heap_headroom();snapshot->runtime_allocations_internal=1;
 static micros_gpio_snapshot_t gpio[4];const micros_graph_gpio_t *bindings;
 snapshot->gpio_count=micros_board_gpio_bindings(&bindings);snapshot->gpio=gpio;
 for(unsigned i=0;i<snapshot->gpio_count;++i) {
  gpio[i]={bindings[i].name,i,(int)bindings[i].pin,(int)bindings[i].output,(int)embedded_gpio_read(i)};
 }
}
