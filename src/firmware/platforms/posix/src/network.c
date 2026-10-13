#include <micros/network.h>
#include <stdio.h>
void micros_wifi_start(void (*ready)(void)) { if (ready) ready(); }
void micros_wifi_poll(void) {}
void micros_wifi_command(char *command) { (void)command; }
size_t micros_wifi_settings_read(char *out,size_t capacity) { return micros_wifi_insights(out,capacity); }
int micros_wifi_settings_write(const uint8_t *body,size_t bytes) { (void)body;(void)bytes;return -4; }
size_t micros_wifi_insights(char *out,size_t capacity) {
 int n=snprintf(out,capacity,"{\"managed\":false,\"provider\":\"os\"}");
 return n<0 || (size_t)n>=capacity ? 0:(size_t)n;
}

int micros_network_fetch_base(const char session[33],const char digest[65]) { (void)session;(void)digest;return 0; }
int micros_network_fetch_busy(void) { return 0; }
int micros_network_configure_relay(const char *host,unsigned port,const char *token) { (void)host;(void)port;(void)token;return -4; }

void micros_platform_network_snapshot(micros_network_snapshot_t *out) { *out=(micros_network_snapshot_t){0};out->profile_index=-1; }
