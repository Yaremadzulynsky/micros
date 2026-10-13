#ifndef MICROS_WIFI_CREDENTIALS_H
#define MICROS_WIFI_CREDENTIALS_H
#include <stddef.h>
#include <stdint.h>
/* IEEE 802.11 SSIDs are at most 32 octets; WPA accepts a 63-byte passphrase
 * or a 64-character hexadecimal PSK. Lengths are explicit, never strlen on wire data. */
#define MICROS_WIFI_SSID_BYTES 32u
#define MICROS_WIFI_PASSWORD_BYTES 64u
#define MICROS_WIFI_CREDENTIALS_VERSION                                                            \
    1u /* Version of the private NVS blob, independent of ABI. */
/** @brief Validated network settings persisted atomically after DHCP succeeds. */
typedef struct {
    uint32_t version;
    uint8_t ssid_bytes;
    uint8_t password_bytes;
    uint8_t ssid[MICROS_WIFI_SSID_BYTES];
    uint8_t password[MICROS_WIFI_PASSWORD_BYTES];
} micros_wifi_credentials_t;
/** Validate a stored credential record; empty password explicitly means an open network. */
int micros_wifi_credentials_valid(const micros_wifi_credentials_t *credentials);
/** Decode two hex fields from USB; '-' represents an empty password. Never logs inputs. */
int micros_wifi_credentials_decode(micros_wifi_credentials_t *credentials, const char *ssid_hex,
                                   const char *password_hex);
/* Four ordered primary networks and exactly one optional fallback. */
#define MICROS_WIFI_PRIMARY_LIMIT 4u
#define MICROS_WIFI_PROFILE_COUNT 5u
#define MICROS_WIFI_PROFILES_VERSION 1u
typedef struct {
    uint32_t version;
    micros_wifi_credentials_t entries[MICROS_WIFI_PROFILE_COUNT];
} micros_wifi_profiles_t;
int micros_wifi_profiles_valid(const micros_wifi_profiles_t *profiles);
int micros_wifi_profiles_put(micros_wifi_profiles_t *profiles,
                            const micros_wifi_credentials_t *credentials, int fallback);
int micros_wifi_profiles_remove(micros_wifi_profiles_t *profiles,
                               const micros_wifi_credentials_t *network);
#endif
