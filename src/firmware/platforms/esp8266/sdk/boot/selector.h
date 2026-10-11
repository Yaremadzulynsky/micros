/* Included only in the pinned ESP8266 SDK bootloader by build_esp8266.py. */
#include "record.h"
#include "esp8266/rom_functions.h"
static int micros_boot_store(micros_boot_record_t r, int old) {
  if (!micros_boot_seal(&r))
    return 0;
  uint32_t address = MICROS_BOOT_ADDRESS + (old == 0 ? 4096 : 0);
  if (SPIEraseSector(address / 4096) != 0 ||
      SPIWrite(address, (const uint8_t *)&r, sizeof(r)) != 0)
    return 0;
  micros_boot_record_t check;
  return SPIRead(address, &check, sizeof(check)) == 0 &&
         micros_boot_valid(&check) && check.sequence == r.sequence;
}
static int micros_boot_select(int sdk_selected) {
  micros_boot_record_t records[2], r;
  if (SPIRead(MICROS_BOOT_ADDRESS, records, sizeof(r)) != 0 ||
      SPIRead(MICROS_BOOT_ADDRESS + 4096, records + 1, sizeof(r)) != 0)
    return sdk_selected;
  int index = micros_boot_latest(records);
  if (index < 0) {
    /* Initial installation starts from the SDK-selected, verified base. */
    if (sdk_selected < 0 || sdk_selected > 1)
      return sdk_selected;
    memset(&r, 0, sizeof(r));
    r.good = sdk_selected;
    r.previous = r.candidate = MICROS_BOOT_NONE;
    micros_boot_store(r, -1);
    return sdk_selected;
  }
  r = records[index];
  if (r.candidate < 2) {
    if (!r.attempts) {
      r.attempts = 1;
      if (micros_boot_store(r, index))
        return r.candidate;
    } else {
      r.candidate = MICROS_BOOT_NONE;
      r.attempts = 0;
      micros_boot_store(r, index);
    }
  }
  return r.good;
}
