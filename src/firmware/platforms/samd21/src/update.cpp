#include <Arduino.h>
#include "device_support.h"
#include "update_support.h"
#include "FreeRTOS.h"
#include "task.h"
#include "support/hardware.h"
#include "network_support.h"
extern "C" {
#include "../sdk/boot/layout.h"
#include "sha256.h"
#include "support/storage.h"
}
#include <string.h>
extern "C" uint8_t __text_start__;
static unsigned running_slot() {return (uintptr_t)&__text_start__==SAMD_BASE_ADDRESS(1)?1:0;}
static int load(samd_boot_record_t &record) {
    samd_boot_record_t records[2];memcpy(records,(void *)SAMD_BASE_JOURNAL,sizeof(records[0]));
    memcpy(records+1,(void *)(SAMD_BASE_JOURNAL+256),sizeof(records[0]));
    int index=samd_boot_latest(records);if(index>=0)record=records[index];return index;
}
static bool store(samd_boot_record_t record,int old) {
    if(record.sequence==UINT32_MAX)return false;
    ++record.sequence;record.crc=samd_boot_crc(&record,offsetof(samd_boot_record_t,crc));record.commit=0x54494d43;
    uint8_t pages[64];memset(pages,255,sizeof(pages));memcpy(pages,&record,sizeof(record));
    uint32_t address=SAMD_BASE_JOURNAL+(old==0?256:0);
    return embedded_flash_erase(address,256) && embedded_flash_write(address,pages,64) && samd_boot_valid((samd_boot_record_t *)address);
}
static unsigned staging=SAMD_NO_SLOT,image_bytes,written;
static uint8_t expected_hash[32];
void embedded_base_ota_status(MicrosPrint &out) {
    samd_boot_record_t r={};int index=load(r);
    out.print("{\"version\":1,\"slot\":");out.print(running_slot());
    out.print(",\"slot_bytes\":81920,\"good\":");out.print(index<0?SAMD_NO_SLOT:r.good);
    out.print(",\"previous\":");out.print(index<0?SAMD_NO_SLOT:r.previous);
    out.print(",\"candidate\":");out.print(index<0?SAMD_NO_SLOT:r.candidate);
    out.print(",\"pending\":");out.print(index>=0&&r.candidate<2?1:0);
    out.print(",\"staging\":");out.print(staging);out.print(",\"written\":");out.print(written);out.print('}');
}
void embedded_base_ota_abort(void) {staging=SAMD_NO_SLOT;written=0;}
bool embedded_base_ota_begin(unsigned slot,unsigned bytes,const uint8_t hash[32]) {
    samd_boot_record_t r;int index=load(r);
    if(index<0 || slot>1 || slot==running_slot() || r.good!=running_slot() || r.candidate<2 ||
       bytes<256 || bytes>SAMD_BASE_BYTES || (bytes&3))return false;
    // Forget any rollback reference before erasing it; current good remains intact.
    r.previous=SAMD_NO_SLOT;r.image_bytes[slot]=0;r.image_crc[slot]=0;
    if(!store(r,index))return false;
    staging=slot;image_bytes=bytes;written=0;memcpy(expected_hash,hash,32);
    extern bool samd_base_flash_erase(uint32_t);
    if(!samd_base_flash_erase(SAMD_BASE_ADDRESS(slot))) {embedded_base_ota_abort();return false;}
    return true;
}
bool embedded_base_ota_write(unsigned offset,const uint8_t *data,unsigned bytes) {
    if(staging>1 || offset>written || !bytes || bytes>256 || bytes%64 ||
       offset>=image_bytes || bytes>SAMD_BASE_BYTES-offset)return false;
    if(offset<written) return bytes<=written-offset &&
        !memcmp((void *)(SAMD_BASE_ADDRESS(staging)+offset),data,bytes);
    extern bool samd_base_flash_write(uint32_t,const uint8_t *,unsigned);
    if(!samd_base_flash_write(SAMD_BASE_ADDRESS(staging)+offset,data,bytes))return false;
    written+=bytes;return true;
}
bool embedded_base_ota_activate(void) {
    if(staging>1 || written<image_bytes)return false;
    uint32_t address=SAMD_BASE_ADDRESS(staging),sp=*(uint32_t *)address,entry=*(uint32_t *)(address+4);
    if(sp<=0x20000000 || sp>0x20008000 || (sp&7) || !(entry&1) ||
       (entry&~1u)<address || (entry&~1u)>=address+image_bytes)return false;
    micros_sha256_t ctx;micros_sha256_init(&ctx);
    for(unsigned offset=0;offset<image_bytes;offset+=256) {
        unsigned n=image_bytes-offset;if(n>256)n=256;
        micros_sha256_update(&ctx,(uint8_t *)address+offset,n);vTaskDelay(1);
    }
    uint8_t hash[32];micros_sha256_finish(&ctx,hash);
    if(memcmp(hash,expected_hash,32))return false;
    samd_boot_record_t r;int index=load(r);if(index<0 || r.good!=running_slot())return false;
    r.image_bytes[staging]=image_bytes;r.image_crc[staging]=samd_boot_crc((void *)address,image_bytes);
    r.candidate=staging;r.attempts=0;
    if(!store(r,index))return false;
    embedded_base_ota_abort();return true;
}
bool samd_base_ota_confirm(void) {
    samd_boot_record_t r;int index=load(r);if(index<0)return false;
    if(r.candidate!=running_slot())return r.good==running_slot();
    r.previous=r.good;r.good=r.candidate;r.candidate=SAMD_NO_SLOT;r.attempts=0;
    return store(r,index);
}
bool embedded_base_ota_rollback(void) {
    samd_boot_record_t r;int index=load(r);
    if(index<0 || r.candidate<2 || r.good!=running_slot() || r.previous>1 || !r.image_bytes[r.previous])return false;
    r.candidate=r.previous;r.previous=SAMD_NO_SLOT;r.attempts=0;return store(r,index);
}

void embedded_base_ota_poll(void) {
    static bool done=false;static uint32_t last=0;
    uint32_t now=millis();if(done || now-last<1000)return;last=now;
    samd_boot_record_t r;int index=load(r);
    if(index<0){embedded_reset();return;}
    if(r.candidate!=running_slot()){done=true;return;}
    if(now>=5000 && embedded_network_online() && samd_base_ota_confirm())done=true;
    else if(now>=30000)embedded_reset();
}

#include <micros/update.h>
#include "support/buffer_print.h"
extern "C" void micros_base_boot(void) { embedded_base_ota_poll(); }
extern "C" int micros_base_application_allowed(const uint8_t hash[32]) { (void)hash;return 1; }
extern "C" int micros_base_bind_application(unsigned bank,const uint8_t hash[32]) { (void)hash;return bank<2; }
extern "C" int micros_base_busy(void) { return staging<2; }
extern "C" void micros_base_abort(void) { embedded_base_ota_abort(); }
extern "C" int micros_base_begin(const uint8_t *header,size_t bytes) {
 if(bytes!=40 || !header || memcmp(header,"MBO1",4))return 0;
 uint32_t length;memcpy(&length,header+4,4);
 return embedded_base_ota_begin(1-running_slot(),length,header+8);
}
extern "C" int micros_base_chunk(uint64_t offset,const uint8_t *data,size_t bytes) {
 return offset<=UINT32_MAX && bytes<=UINT32_MAX && embedded_base_ota_write((unsigned)offset,data,(unsigned)bytes);
}
extern "C" int micros_base_finish(void) { return embedded_base_ota_activate(); }
extern "C" size_t micros_base_status(char *out,size_t capacity) {
 MicrosBufferPrint writer(out,capacity);embedded_base_ota_status(writer);return writer.size();
}

extern "C" int micros_base_pending(void) { samd_boot_record_t record;return load(record)>=0 && record.candidate<2; }
extern "C" int micros_base_confirm(void) { return samd_base_ota_confirm(); }

extern "C" int micros_base_rollback(void) { return embedded_base_ota_rollback(); }
