#include "layout.h"
#include <stddef.h>
uint32_t samd_boot_crc(const void *data, uint32_t bytes) {
    const uint8_t *p=data; uint32_t crc=~0u;
    while(bytes--) {crc^=*p++; for(unsigned i=0;i<8;i++) crc=(crc>>1)^((0u-(crc&1u))&0xedb88320u);}
    return ~crc;
}
int samd_boot_valid(const samd_boot_record_t *r) {
    if(r->magic!=SAMD_BOOT_MAGIC || !r->sequence || r->commit!=0x54494d43u ||
       r->crc!=samd_boot_crc(r,offsetof(samd_boot_record_t,crc)) || r->good>1 ||
       (r->previous>1 && r->previous!=SAMD_NO_SLOT) ||
       (r->candidate>1 && r->candidate!=SAMD_NO_SLOT) ||
       (r->candidate<2 && r->candidate==r->good) || r->attempts>1) return 0;
    for(unsigned i=0;i<2;i++) if(r->image_bytes[i]>SAMD_BASE_BYTES || (r->image_bytes[i]&3)) return 0;
    return r->image_bytes[r->good]>=256;
}
int samd_boot_latest(const samd_boot_record_t r[2]) {
    int a=samd_boot_valid(r),b=samd_boot_valid(r+1);
    return !a?(b?1:-1):(!b || r[0].sequence>=r[1].sequence?0:1);
}
