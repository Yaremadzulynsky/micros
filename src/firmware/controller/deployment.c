#include <micros/memory.h>
#include <micros/storage.h>
#include <micros/platform.h>
#include <micros/capabilities.h>
#include "image.h"
#include "sha256.h"
#include <stdlib.h>
/* Streaming keeps image size independent of the controller's RAM requirement.
 * Native descriptors are admitted by the loader before any hook executes. */
int micros_deployment_hash(unsigned bank,uint8_t hash[MICROS_ACTIVATION_HASH_BYTES]) {
    micros_device_graph_t *graph=micros_management_allocate(sizeof(*graph));
    if(!graph)return 0;
    if(!micros_storage_read_graph(bank,graph) || graph->service_count>4 || !graph->service_count ||
       graph->magic!=MICROS_GRAPH_MAGIC || graph->version!=MICROS_GRAPH_VERSION || graph->bank!=bank ||
       graph->checksum!=micros_crc32((const uint8_t*)graph,offsetof(micros_device_graph_t,checksum))) {micros_management_free(graph);return 0;}
    micros_sha256_t state;micros_sha256_init(&state);micros_sha256_update(&state,graph,sizeof(*graph));
    unsigned count=graph->service_count,slots[4];
    for(unsigned i=0;i<count;++i)slots[i]=graph->services[i].slot;
    micros_management_free(graph);
    for(unsigned i=0;i<count;++i) {
        uint32_t header[16];unsigned slot=slots[i];
        if(slot>=MICROS_BOARD_IMAGE_SLOTS || !micros_storage_read_image_part(bank,slot,0,header,sizeof(header)) ||
           header[0]!=MICROS_IMAGE_MAGIC || header[7]>MICROS_BOARD_CODE_BYTES || header[8]>MICROS_BOARD_DATA_BYTES ||
           header[7]+header[8]>MICROS_BOARD_IMAGE_BYTES-64)return 0;
        size_t total=64+header[7]+header[8];uint8_t chunk[256];
        for(size_t offset=0;offset<total;offset+=sizeof(chunk)) {
            size_t bytes=total-offset<sizeof(chunk)?total-offset:sizeof(chunk);
            if(!micros_storage_read_image_part(bank,slot,offset,chunk,bytes))return 0;
            micros_sha256_update(&state,chunk,bytes);
            if(offset%4096==0)micros_controller_yield();
        }
    }
    micros_sha256_finish(&state,hash);return 1;
}
