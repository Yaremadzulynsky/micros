/* Link-only fixture; never a working platform. */
#include <micros/platform.h>
#include <micros/storage.h>
#include <micros/transport.h>
#include <micros/network.h>
#include <micros/update.h>
#include <micros/telemetry.h>
int micros_storage_init(void) { return 0; }
uint8_t *micros_storage_read_image(unsigned bank,unsigned slot,size_t *bytes) { return NULL; }
int micros_storage_write_image(unsigned bank,unsigned slot,const void *image,size_t bytes) { return 0; }
int micros_storage_read_graph(unsigned bank,micros_device_graph_t *graph) { return 0; }
int micros_storage_write_graph(unsigned bank,const micros_device_graph_t *graph) { return 0; }
micros_activation_record_t micros_storage_selection(void) { return micros_activation_empty(); }
int micros_storage_select(micros_activation_record_t next) { return 0; }
void micros_storage_fault_arm(unsigned boundary) {}
void micros_storage_fault_boundary(unsigned boundary) {}
int micros_storage_prepare(unsigned bank) { return 0; }
int micros_storage_rebind_images(unsigned bank) { return 0; }
int micros_storage_image_path(unsigned bank,unsigned slot,char *out,size_t bytes) { return 0; }
int micros_storage_write_image_part(unsigned bank,unsigned slot,size_t offset,const void *data,size_t bytes) { return 0; }

int micros_storage_read_image_part(unsigned bank,unsigned slot,size_t offset,void *out,size_t bytes) { return 0; }
