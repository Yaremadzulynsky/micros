#ifndef MICROS_NETWORK_H
#define MICROS_NETWORK_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct {
    int connected, configured, relay_configured;
    unsigned stack_free;
    const char *stage, *mac, *ip, *firmware;
    int relay_http, rssi_known, rssi_dbm, profile_index;
    unsigned disconnects, disconnect_reason;
} micros_network_snapshot_t;
void micros_platform_network_snapshot(micros_network_snapshot_t *snapshot);

#define MICROS_WIFI_SETTINGS_BYTES 404u
/* Three ordered primary records and one fallback; passwords never returned. */
size_t micros_wifi_settings_read(char *output, size_t capacity);
int micros_wifi_settings_write(const uint8_t *body, size_t bytes);
/** @brief Non-secret controller-owned Wi-Fi snapshot as JSON. Returns bytes or zero on overflow. */
size_t micros_wifi_insights(char *output, size_t capacity);
/** Initialize Wi-Fi from private platform settings. Invokes ready on the controller task after DHCP. */
void micros_wifi_start(void (*ready)(void));
/** Advance connection tests, retries and scan completion without blocking service workers. */
void micros_wifi_poll(void);
/** Handle a physical console command and print a bounded WIFI JSON response; never echo secrets. */
void micros_wifi_command(char *command);
/** Optional authenticated base download; returns 1 when accepted, 0 if unavailable. */
int micros_network_fetch_base(const char session[33], const char digest[65]);
int micros_network_fetch_busy(void);
/** Persist an endpoint and token; return 0 on success, an error otherwise. */
int micros_network_configure_relay(const char *host, unsigned port, const char *token);
#ifdef __cplusplus
}
#endif
#endif
