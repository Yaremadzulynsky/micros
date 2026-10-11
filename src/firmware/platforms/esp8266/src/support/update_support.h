#ifndef MICROS_SUPPORT_UPDATE_H
#define MICROS_SUPPORT_UPDATE_H
#include "print.h"
/* Implemented by base_ota.cpp. */
void embedded_base_ota_poll();
void embedded_base_ota_status(MicrosPrint &out);
bool embedded_base_ota_begin(unsigned slot, unsigned bytes, const uint8_t *hash);
bool embedded_base_ota_write(unsigned offset, const uint8_t *data, unsigned bytes);
bool embedded_base_ota_activate();
bool embedded_base_ota_rollback();
void embedded_base_ota_abort();
#endif
