#include <micros/memory.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "support/storage.h"
#include "esp_app_format.h"
#include "esp_ota_ops.h"
#include "esp_spi_flash.h"
#include <string.h>
uint8_t embedded_data[4][EMBEDDED_DATA_BYTES] __attribute__((aligned(16)));
const uint32_t embedded_profile __attribute__((used)) = 6;
const embedded_graph_t *embedded_graph(uint32_t bank) {
  return bank < 2 ? (const embedded_graph_t *)(EMBEDDED_BANK_BASE +
                                               bank * EMBEDDED_BANK_BYTES)
                  : NULL;
}
uint32_t embedded_image_address(uint32_t bank, uint32_t slot) {
  return EMBEDDED_BANK_BASE + bank * EMBEDDED_BANK_BYTES +
         EMBEDDED_GRAPH_BYTES + slot * EMBEDDED_SLOT_BYTES;
}
void embedded_base_hash(uint8_t hash[32]) {
  memcpy(hash, esp_ota_get_app_description()->app_elf_sha256, 32);
}
static int physical(uint32_t address, size_t bytes, uint32_t *offset) {
  if (address < EMBEDDED_BANK_BASE || address >= 0x40300000 ||
      bytes > 0x40300000 - address)
    return 0;
  *offset = (esp_ota_get_running_partition()->address & ~0xfffffu) +
            (address - 0x40200000);
  return 1;
}
int embedded_flash_erase(uint32_t address, size_t bytes) {
  uint32_t offset;
  return !(address % 4096) && !(bytes % 4096) &&
         physical(address, bytes, &offset) &&
         spi_flash_erase_range(offset, bytes) == ESP_OK;
}
int embedded_flash_write(uint32_t address, const uint8_t *data, size_t bytes) {
  uint32_t offset;
  return !(address % 4) && !(bytes % 4) && physical(address, bytes, &offset) &&
         spi_flash_write(offset, data, bytes) == ESP_OK;
}

void *embedded_image_data(unsigned slot) { return slot < 4 ? embedded_data[slot] : NULL; }
int embedded_pin_valid(unsigned pin) { return pin <= 16 && !(pin >= 6 && pin <= 11) && pin != 1 && pin != 3; }
int embedded_entry_valid(uint32_t entry, uint32_t base, uint32_t bytes) { return entry >= base && entry < base + bytes; }
void embedded_storage_yield(void) { if (xTaskGetSchedulerState() == taskSCHEDULER_RUNNING) vTaskDelay(1); }

/* Logical image-store contract. Flash addresses are private to this backend. */
#include <micros/storage.h>
#include <micros/platform.h>
#include <micros/capabilities.h>
#include "image.h"
#include <stdlib.h>
#include <stdio.h>
extern void platform_journal_read(micros_activation_record_t records[2]);
extern int platform_journal_write(unsigned sector,const micros_activation_record_t *record);
static micros_activation_record_t store_selection;
static int store_sector=-1;
static unsigned store_fault;
int micros_storage_init(void) {
 micros_activation_record_t records[2];platform_journal_read(records);
 store_sector=micros_activation_latest(records);
 store_selection=store_sector<0?micros_activation_empty():records[store_sector];return 1;
}
int micros_storage_image_path(unsigned bank,unsigned slot,char *path,size_t capacity) {
 if(bank>=2 || slot>=4 || capacity<4)return 0;
 path[0]=(char)('0'+bank);path[1]=':';path[2]=(char)('0'+slot);path[3]=0;return 1;
}
int micros_storage_prepare(unsigned bank) {
 return bank<2 && bank!=store_selection.good && !store_selection.pending &&
 embedded_flash_erase(EMBEDDED_BANK_BASE+bank*EMBEDDED_BANK_BYTES,EMBEDDED_BANK_BYTES);
}
static int flash_bytes(uint32_t address,const void *input,size_t bytes) {
 const uint8_t *data=input;
 for(size_t offset=0;offset<bytes;offset+=64) {
  uint8_t page[64];memset(page,255,sizeof(page));
  size_t n=bytes-offset<64?bytes-offset:64;memcpy(page,data+offset,n);
  if(!embedded_flash_write(address+(uint32_t)offset,page,64))return 0;
  embedded_storage_yield();
 }
 return 1;
}
uint8_t *micros_storage_read_image(unsigned bank,unsigned slot,size_t *bytes) {
 if(bank>=2 || slot>=4 || !bytes)return NULL;
 const uint32_t *header=(const void *)(uintptr_t)embedded_image_address(bank,slot);
 if(header[0]!=MICROS_IMAGE_MAGIC || header[7]>EMBEDDED_SLOT_BYTES-64 || header[8]>EMBEDDED_SLOT_BYTES-64-header[7])return NULL;
 *bytes=64+header[7]+header[8];uint8_t *data=micros_management_allocate(*bytes);
 if(data)memcpy(data,header,*bytes);
 return data;
}
int micros_storage_write_image(unsigned bank,unsigned slot,const void *data,size_t bytes) {
 return bank<2 && slot<4 && bank!=store_selection.good && !store_selection.pending &&
 bytes>=64 && bytes<=EMBEDDED_SLOT_BYTES &&
 flash_bytes(embedded_image_address(bank,slot),data,bytes);
}
int micros_storage_read_graph(unsigned bank,micros_device_graph_t *graph) {
 if(bank>=2)return 0;
 memcpy(graph,embedded_graph(bank),sizeof(*graph));return 1;
}
int micros_storage_write_graph(unsigned bank,const micros_device_graph_t *graph) {
 return bank<2 && bank!=store_selection.good && !store_selection.pending &&
 flash_bytes(EMBEDDED_BANK_BASE+bank*EMBEDDED_BANK_BYTES,graph,sizeof(*graph));
}
micros_activation_record_t micros_storage_selection(void) { return store_selection; }
int micros_storage_select(micros_activation_record_t next) {
 unsigned sector=store_sector==0?1:0;
 if(!micros_activation_seal(&next,store_selection.sequence) || !platform_journal_write(sector,&next))return 0;
 store_selection=next;store_sector=(int)sector;return 1;
}
int micros_storage_rebind_images(unsigned bank) { (void)bank;return 0; }
void micros_storage_fault_arm(unsigned boundary) { store_fault=boundary; }
void micros_storage_fault_boundary(unsigned boundary) { if(store_fault && boundary==store_fault)micros_controller_reset(); }
int embedded_image_validate(uint32_t bank,uint32_t slot,uint32_t bytes) {
 if(bank>=2 || slot>=4 || bytes>EMBEDDED_SLOT_BYTES)return 0;
 const uint8_t *data=(const void*)(uintptr_t)embedded_image_address(bank,slot);
 micros_image_t image;
 return !micros_image_validate(data,bytes,EMBEDDED_TARGET,&image) &&
        image.code_base==embedded_image_address(bank,slot)+64 &&
        !micros_board_validate_bytes(data,bytes,slot);
}
int micros_storage_write_image_part(unsigned bank,unsigned slot,size_t offset,const void *data,size_t bytes) {
 return bank<2 && slot<4 && bank!=store_selection.good && !store_selection.pending &&
 offset%64==0 && offset<EMBEDDED_SLOT_BYTES && bytes<=EMBEDDED_SLOT_BYTES-offset &&
 flash_bytes(embedded_image_address(bank,slot)+(uint32_t)offset,data,bytes);
}

int micros_storage_read_image_part(unsigned bank,unsigned slot,size_t offset,void *output,size_t bytes) {
    if(bank>=2 || slot>=4 || offset>EMBEDDED_SLOT_BYTES || bytes>EMBEDDED_SLOT_BYTES-offset)return 0;
    memcpy(output,(const void*)(uintptr_t)(embedded_image_address(bank,slot)+offset),bytes);return 1;
}
