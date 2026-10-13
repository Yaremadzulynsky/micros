#ifndef MICROS_SUPPORT_PORT_H
#define MICROS_SUPPORT_PORT_H
#include <micros/capabilities.h>
#include "flash_support.h"
#ifdef __cplusplus
#include "network_support.h"
#include "update_support.h"
extern "C" {
#endif
#include "activation.h"
#include "runtime.h"
#include <micros/platform.h>
#ifdef __cplusplus
}
#endif
MICROS_REQUIRE_CAPABILITY(NATIVE_SERVICES);
MICROS_REQUIRE_CAPABILITY(PERSISTENT_STORAGE);
MICROS_REQUIRE_CAPABILITY(BASE_UPDATE);
/* Implemented by support/system.cpp. No target SDK types cross this boundary. */
#ifdef __cplusplus
extern "C" {
#endif
void embedded_gpio_bind(uint32_t line, uint32_t pin, uint32_t output);
uint32_t embedded_gpio_read(uint32_t line);
int embedded_gpio_write(uint32_t line, uint32_t level);
void embedded_log(const uint8_t *data, size_t bytes);
size_t embedded_logs(uint8_t *data, size_t capacity);
size_t embedded_heap_free(void);
size_t embedded_heap_headroom(void);
uint32_t embedded_heap_total(void);
unsigned embedded_reset_cause(void);
void embedded_reset(void);
void embedded_console_begin(void);
void embedded_bootloader(void);
void embedded_idle(void);
void embedded_controller_wait(void);
void embedded_network_identity_bytes(uint8_t identity[6]);

#ifdef __cplusplus
}

/* Yield between controller polls so service tasks can run. */

/* Remaining controller stack in bytes, or zero when unavailable. */
size_t embedded_controller_stack_free();
uint32_t embedded_target_profile();

void embedded_journal_read(micros_activation_record_t records[2]);
bool embedded_journal_write(unsigned sector, const micros_activation_record_t &record);
/* Startup calls begin before the shared controller. Console returns the same
 * stream object for the lifetime of the base; available/read are nonblocking. */

MicrosPrint &embedded_console();
int embedded_console_available();
int embedded_console_read();
void embedded_console_flush();
/* Implemented by the shared controller, called by the target startup. */
extern "C" void embedded_management(void *);
#endif /* __cplusplus */
#endif
