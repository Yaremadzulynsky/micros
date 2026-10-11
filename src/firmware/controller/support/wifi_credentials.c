#include "wifi_credentials.h"
#include <string.h>
static int hex_digit(char character)
{
    if (character >= '0' && character <= '9')
        return character - '0';
    if (character >= 'a' && character <= 'f')
        return character - 'a' + 10;
    if (character >= 'A' && character <= 'F')
        return character - 'A' + 10;
    return -1;
}
int micros_wifi_credentials_valid(const micros_wifi_credentials_t *credentials)
{
    if (credentials->version != MICROS_WIFI_CREDENTIALS_VERSION || !credentials->ssid_bytes ||
        credentials->ssid_bytes > MICROS_WIFI_SSID_BYTES ||
        credentials->password_bytes > MICROS_WIFI_PASSWORD_BYTES)
        return 0;
    if (memchr(credentials->ssid, 0, credentials->ssid_bytes) ||
        memchr(credentials->password, 0, credentials->password_bytes))
        return 0; /* ESP-IDF station configuration uses NUL-terminated passphrases. */
    if (credentials->password_bytes && credentials->password_bytes < 8)
        return 0; /* WPA/WPA2 passphrases require at least eight octets. */
    if (credentials->password_bytes == MICROS_WIFI_PASSWORD_BYTES) {
        for (size_t index = 0; index < credentials->password_bytes; ++index)
            if (hex_digit((char)credentials->password[index]) < 0)
                return 0;
    }
    return 1;
}
static int decode_field(const char *hex, uint8_t *output, size_t capacity, uint8_t *bytes)
{
    size_t length = strlen(hex);
    if (length % 2 || length > capacity * 2)
        return 0;
    for (size_t index = 0; index < length / 2; ++index) {
        int high = hex_digit(hex[index * 2]), low = hex_digit(hex[index * 2 + 1]);
        if (high < 0 || low < 0)
            return 0;
        output[index] = (uint8_t)((high << 4) | low);
    }
    *bytes = (uint8_t)(length / 2);
    return 1;
}
int micros_wifi_credentials_decode(micros_wifi_credentials_t *credentials, const char *ssid_hex,
                                   const char *password_hex)
{
    memset(credentials, 0, sizeof(*credentials));
    credentials->version = MICROS_WIFI_CREDENTIALS_VERSION;
    if (!decode_field(ssid_hex, credentials->ssid, sizeof(credentials->ssid),
                      &credentials->ssid_bytes) ||
        (strcmp(password_hex, "-") &&
         !decode_field(password_hex, credentials->password, sizeof(credentials->password),
                       &credentials->password_bytes)) ||
        !micros_wifi_credentials_valid(credentials)) {
        memset(credentials, 0, sizeof(*credentials));
        return 0;
    }
    return 1;
}

static int same_network(const micros_wifi_credentials_t *a, const micros_wifi_credentials_t *b)
{
    return a->ssid_bytes && a->ssid_bytes == b->ssid_bytes &&
           !memcmp(a->ssid, b->ssid, a->ssid_bytes);
}
int micros_wifi_profiles_valid(const micros_wifi_profiles_t *profiles)
{
    if (profiles->version != MICROS_WIFI_PROFILES_VERSION)
        return 0;
    int gap = 0;
    for (unsigned i = 0; i < MICROS_WIFI_PROFILE_COUNT; ++i) {
        const micros_wifi_credentials_t *entry = &profiles->entries[i];
        if (!entry->ssid_bytes) {
            micros_wifi_credentials_t empty = {0};
            if (memcmp(entry, &empty, sizeof(empty)))
                return 0;
            if (i < MICROS_WIFI_PRIMARY_LIMIT)
                gap = 1;
            continue;
        }
        if (!micros_wifi_credentials_valid(entry) || (gap && i < MICROS_WIFI_PRIMARY_LIMIT))
            return 0;
        for (unsigned j = 0; j < i; ++j)
            if (same_network(entry, &profiles->entries[j]))
                return 0;
    }
    return 1;
}
int micros_wifi_profiles_remove(micros_wifi_profiles_t *profiles,
                               const micros_wifi_credentials_t *network)
{
    for (unsigned i = 0; i < MICROS_WIFI_PROFILE_COUNT; ++i) {
        if (!same_network(&profiles->entries[i], network))
            continue;
        unsigned last = i < MICROS_WIFI_PRIMARY_LIMIT ? MICROS_WIFI_PRIMARY_LIMIT - 1 : i;
        for (unsigned j = i; j < last; ++j)
            profiles->entries[j] = profiles->entries[j + 1];
        memset(&profiles->entries[last], 0, sizeof(profiles->entries[last]));
        return 1;
    }
    return 0;
}
int micros_wifi_profiles_put(micros_wifi_profiles_t *profiles,
                            const micros_wifi_credentials_t *credentials, int fallback)
{
    if (!micros_wifi_profiles_valid(profiles) || !micros_wifi_credentials_valid(credentials))
        return 0;
    unsigned target = MICROS_WIFI_PRIMARY_LIMIT;
    if (!fallback) {
        for (unsigned i = 0; i < MICROS_WIFI_PRIMARY_LIMIT; ++i)
            if (!profiles->entries[i].ssid_bytes || same_network(&profiles->entries[i], credentials)) {
                target = i;
                break;
            }
        if (target == MICROS_WIFI_PRIMARY_LIMIT)
            return 0;
        /* Moving a fallback to the primary list never creates a duplicate. */
        if (same_network(&profiles->entries[MICROS_WIFI_PRIMARY_LIMIT], credentials))
            memset(&profiles->entries[MICROS_WIFI_PRIMARY_LIMIT], 0, sizeof(*credentials));
    } else {
        micros_wifi_profiles_remove(profiles, credentials);
    }
    profiles->entries[target] = *credentials;
    return 1;
}
