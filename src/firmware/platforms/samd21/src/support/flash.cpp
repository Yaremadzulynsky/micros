#include <Arduino.h>
extern "C"
{
#include "storage.h"
#include "../../sdk/boot/layout.h"
}
#include <string.h>
static int wait_ready(void)
{
    unsigned limit = 4000000;
    while (!NVMCTRL->INTFLAG.bit.READY && --limit)
    {
    }
    if (!limit)
        return 0;
    return !(NVMCTRL->STATUS.reg &
             (NVMCTRL_STATUS_PROGE | NVMCTRL_STATUS_LOCKE | NVMCTRL_STATUS_NVME));
}
static int erase(uint32_t address, size_t bytes)
{
    if (address < SAMD_JOURNAL_BASE || address > 0x40000u || bytes > 0x40000u - address ||
        (address | bytes) % 256)
        return 0;
    for (size_t offset = 0; offset < bytes; offset += 256)
    {
        uint32_t mask = __get_PRIMASK();
        __disable_irq();
        NVMCTRL->STATUS.reg |= NVMCTRL_STATUS_PROGE | NVMCTRL_STATUS_LOCKE | NVMCTRL_STATUS_NVME;
        NVMCTRL->ADDR.reg = (address + offset) / 2;
        NVMCTRL->CTRLA.reg = NVMCTRL_CTRLA_CMDEX_KEY | NVMCTRL_CTRLA_CMD_ER;
        int ok = wait_ready();
        __set_PRIMASK(mask);
        if (!ok)
            return 0;
    }
    return 1;
}
static int write(uint32_t address, const uint8_t *data, size_t bytes)
{
    if (address < SAMD_JOURNAL_BASE || address > 0x40000u || bytes > 0x40000u - address ||
        (address | bytes) % 64)
        return 0;
    for (size_t offset = 0; offset < bytes; offset += 64)
    {
        uint32_t mask = __get_PRIMASK();
        __disable_irq();
        NVMCTRL->CTRLB.bit.MANW = 1;
        NVMCTRL->STATUS.reg |= NVMCTRL_STATUS_PROGE | NVMCTRL_STATUS_LOCKE | NVMCTRL_STATUS_NVME;
        NVMCTRL->CTRLA.reg = NVMCTRL_CTRLA_CMDEX_KEY | NVMCTRL_CTRLA_CMD_PBC;
        if (!wait_ready())
        {
            __set_PRIMASK(mask);
            return 0;
        }
        volatile uint32_t *destination = (volatile uint32_t *)(uintptr_t)(address + offset);
        for (unsigned word = 0; word < 16; ++word)
        {
            uint32_t value;
            memcpy(&value, data + offset + word * 4, 4);
            destination[word] = value;
        }
        NVMCTRL->ADDR.reg = (address + offset) / 2;
        NVMCTRL->CTRLA.reg = NVMCTRL_CTRLA_CMDEX_KEY | NVMCTRL_CTRLA_CMD_WP;
        int ok = wait_ready();
        __set_PRIMASK(mask);
        if (!ok)
            return 0;
        if (memcmp((const void *)(uintptr_t)(address + offset), data + offset, 64))
            return 0;
    }
    return 1;
}

static bool storage_range(uint32_t address,size_t bytes) {
    return address>=SAMD_SERVICE_JOURNAL && address<=0x40000u && bytes<=0x40000u-address &&
        (address+bytes<=0x4000u || address>=SAMD_SERVICE_BASE);
}
extern "C" int embedded_flash_erase(uint32_t address,size_t bytes) {
    return storage_range(address,bytes) && erase(address,bytes);
}
extern "C" int embedded_flash_write(uint32_t address,const uint8_t *data,size_t bytes) {
    return storage_range(address,bytes) && write(address,data,bytes);
}
extern "C" uint8_t __text_start__;
static bool inactive_range(uint32_t address,size_t bytes) {
    uint32_t inactive=(uintptr_t)&__text_start__==SAMD_BASE_ADDRESS(0)?SAMD_BASE_ADDRESS(1):SAMD_BASE_ADDRESS(0);
    return address>=inactive && address<=inactive+SAMD_BASE_BYTES && bytes<=inactive+SAMD_BASE_BYTES-address;
}
bool samd_base_flash_erase(uint32_t address) {return inactive_range(address,SAMD_BASE_BYTES) && erase(address,SAMD_BASE_BYTES);}
bool samd_base_flash_write(uint32_t address,const uint8_t *data,unsigned bytes) {return inactive_range(address,bytes) && write(address,data,bytes);}
