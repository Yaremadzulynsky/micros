/* Link-only fixture; never a working platform. */
#include <micros/platform.h>
#include <micros/storage.h>
#include <micros/transport.h>
#include <micros/network.h>
#include <micros/update.h>
#include <micros/telemetry.h>
size_t micros_wifi_settings_read(char *output,size_t capacity) { return 0; }
int micros_wifi_settings_write(const uint8_t *body,size_t bytes) { return 0; }
size_t micros_wifi_insights(char *output,size_t capacity) { return 0; }
void micros_wifi_start(void (*ready)(void)) {}
void micros_wifi_poll(void) {}
void micros_wifi_command(char *command) {}
void micros_platform_network_snapshot(micros_network_snapshot_t *snapshot) {}

int micros_network_fetch_base(const char session[33],const char digest[65]) { (void)session;(void)digest;return 0; }
int micros_network_fetch_busy(void) { return 0; }
int micros_network_configure_relay(const char *host,unsigned port,const char *token) { (void)host;(void)port;(void)token;return -4; }
