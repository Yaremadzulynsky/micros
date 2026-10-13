#include "layout.h"
#include <stddef.h>
#define REG8(a) (*(volatile uint8_t *)(a))
#define REG16(a) (*(volatile uint16_t *)(a))
#define REG32(a) (*(volatile uint32_t *)(a))
static int ready(void) {
    unsigned n=4000000; while(!(REG8(0x41004014u)&1) && --n) {}
    return n && !(REG16(0x41004018u)&0x1c);
}
static int command(uint16_t cmd,uint32_t address) {
    if(cmd==2)REG16(0x41004018u)=0x1c;
    if(cmd!=0x44)REG32(0x4100401cu)=address/2;
    REG16(0x41004000u)=0xa500u|cmd;
    return ready();
}
static int store(samd_boot_record_t *r,int old) {
    if(r->sequence==0xffffffffu) return 0;
    r->sequence++;r->crc=samd_boot_crc(r,offsetof(samd_boot_record_t,crc));r->commit=0x54494d43u;
    uint32_t address=SAMD_BASE_JOURNAL+(old==0?256:0);
    if(!command(2,address))return 0;
    REG32(0x41004004u)|=0x80;
    for(unsigned page=0;page<1;page++) {
        if(!command(0x44,0))return 0;
        for(unsigned w=0;w<16;w++) {
            unsigned i=page*16+w;
            REG32(address+i*4)=i<sizeof(*r)/4?((uint32_t *)r)[i]:0xffffffffu;
        }
        if(!command(4,address+page*64))return 0;
    }
    return samd_boot_valid((const samd_boot_record_t *)address);
}
static int image_valid(const samd_boot_record_t *r,unsigned slot) {
    if(slot>1 || r->image_bytes[slot]<256)return 0;
    uint32_t address=SAMD_BASE_ADDRESS(slot),sp=REG32(address),entry=REG32(address+4);
    return sp>0x20000000u && sp<=0x20008000u && !(sp&7) && (entry&1) &&
        (entry&~1u)>=address && (entry&~1u)<address+r->image_bytes[slot] &&
        samd_boot_crc((void *)address,r->image_bytes[slot])==r->image_crc[slot];
}
__attribute__((naked,noreturn)) static void jump(uint32_t address __attribute__((unused))) {
    __asm volatile("ldr r1,[r0]\nldr r2,[r0,#4]\nldr r3,=0xe000ed08\nstr r0,[r3]\nmovs r0,#0\nmsr control,r0\nmsr msp,r1\ndsb\nisb\ncpsie i\nbx r2");
}
__attribute__((noreturn)) static void usb_recovery(void) {
    REG32(0x20007ffcu)=0x07738135u; /* Arduino double-tap marker. */
    REG32(0xe000ed0cu)=0x05fa0004u;for(;;){}
}
void boot_start(void) {
    __asm volatile("cpsid i");
    REG32(0xe000e010u)=0;REG32(0xe000e180u)=0xffffffffu;REG32(0xe000e280u)=0xffffffffu;
    /* Disable a retained watchdog before CRC scans and journal writes. */
    REG8(0x40001000u)=0;while(REG8(0x40001007u)&0x80){}
    samd_boot_record_t records[2];
    for(unsigned j=0;j<2;j++)for(unsigned i=0;i<sizeof(records[0])/4;i++)
        ((uint32_t *)&records[j])[i]=REG32(SAMD_BASE_JOURNAL+j*256+i*4);
    int index=samd_boot_latest(records);if(index<0)usb_recovery();
    samd_boot_record_t r=records[index];unsigned slot=r.good;
    if(r.candidate<2) {
        if(!r.attempts && image_valid(&r,r.candidate)) {
            r.attempts=1;if(!store(&r,index))usb_recovery();index=1-index;slot=r.candidate;
        } else {r.candidate=SAMD_NO_SLOT;r.attempts=0;if(!store(&r,index))usb_recovery();index=1-index;}
    }
    if(!image_valid(&r,slot)) {
        slot=slot!=r.good?r.good:r.previous;if(!image_valid(&r,slot))usb_recovery();
        r.good=slot;r.previous=SAMD_NO_SLOT;r.candidate=SAMD_NO_SLOT;r.attempts=0;
        if(!store(&r,index))usb_recovery();
    }
    /* System reset leaves watchdog clock configuration at its reset source.
       A bounded startup watchdog protects candidates before Arduino setup. */
    REG32(0x40000c08u)=4u|(32u<<8);while(REG8(0x40000c01u)&0x80){}
    REG32(0x40000c04u)=4u|(3u<<8)|(1u<<16);while(REG8(0x40000c01u)&0x80){}
    REG16(0x40000c02u)=3u|(4u<<8)|(1u<<14);while(REG8(0x40000c01u)&0x80){}
    REG8(0x40001001u)=0x0b; REG8(0x40001000u)=2;
    while(REG8(0x40001007u)&0x80){}
    jump(SAMD_BASE_ADDRESS(slot));
}
__attribute__((section(".vectors"),used)) const uintptr_t vectors[2]={0x20008000u,(uintptr_t)boot_start};
void *memcpy(void *to,const void *from,size_t n) {uint8_t *d=to;const uint8_t *s=from;while(n--)*d++=*s++;return to;}
