#ifndef MICROS_STORAGE_H
#define MICROS_STORAGE_H
#include "activation.h"
#include <micros/deployment.h>
#ifdef __cplusplus
extern "C" {
#endif
/** Initialize only the service-store and activation partition handles. */
int micros_storage_init(void);
int micros_storage_prepare(unsigned bank);
/** Write a sequential bounded image fragment after prepare; offset is an image
 * byte offset, independent of the target's erase/page geometry. */
int micros_storage_write_image_part(unsigned bank,unsigned slot,size_t offset,const void *data,size_t bytes);
/** Resolve a logical image to the loader's platform-owned locator. */
int micros_storage_image_path(unsigned bank, unsigned slot, char *path, size_t capacity);
/** Optional live replacement: 1 succeeds, 0 leaves the old images intact,
 * -1 requires process/device recovery before native execution resumes. */
int micros_storage_rebind_images(unsigned bank);
/** Read exact image bytes without allocating the complete image. */
int micros_storage_read_image_part(unsigned bank,unsigned slot,size_t offset,void *output,size_t bytes);
/** Read one bounded allocated native image; caller frees the returned buffer. */
uint8_t *micros_storage_read_image(unsigned bank, unsigned slot, size_t *bytes);
int micros_storage_write_image(unsigned bank, unsigned slot, const void *image, size_t bytes);
int micros_storage_read_graph(unsigned bank, micros_device_graph_t *graph);
int micros_storage_write_graph(unsigned bank, const micros_device_graph_t *graph);
micros_activation_record_t micros_storage_selection(void);
/** Program the alternate journal sector, verify it, then update the cached selection. */
int micros_storage_select(micros_activation_record_t next);
/** Arm one physical-development reset boundary; cleared by reset, never persisted. */
void micros_storage_fault_arm(unsigned boundary);
void micros_storage_fault_boundary(unsigned boundary);
#ifdef __cplusplus
}
#endif
#endif
