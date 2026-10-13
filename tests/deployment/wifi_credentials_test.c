#include "wifi_credentials.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
int main(void)
{
    micros_wifi_credentials_t credentials;
    assert(micros_wifi_credentials_decode(&credentials, "74657374", "70617373776f7264"));
    assert(credentials.ssid_bytes == 4 && credentials.password_bytes == 8);
    assert(micros_wifi_credentials_valid(&credentials));
    assert(micros_wifi_credentials_decode(&credentials, "74657374", "-"));
    assert(!credentials.password_bytes);
    assert(!micros_wifi_credentials_decode(&credentials, "", "-"));
    assert(!micros_wifi_credentials_decode(&credentials, "0", "-"));
    assert(!micros_wifi_credentials_decode(&credentials, "zz", "-"));
    assert(!micros_wifi_credentials_decode(&credentials, "00", "-"));
    assert(!micros_wifi_credentials_decode(&credentials, "74657374", "61"));
    assert(!micros_wifi_credentials_decode(&credentials, "74657374", "0000000000000000"));
    char ssid_hex[67], password_hex[131];
    memset(ssid_hex, '6', sizeof(ssid_hex));
    ssid_hex[64] = 0; /* A full 32-byte SSID is permitted without a terminator in the record. */
    memset(password_hex, '6', sizeof(password_hex));
    password_hex[126] = 0;
    assert(micros_wifi_credentials_decode(&credentials, ssid_hex, password_hex));
    assert(credentials.ssid_bytes == 32 && credentials.password_bytes == 63);
    password_hex[126] = password_hex[127] = '6';
    password_hex[128] = 0;
    assert(micros_wifi_credentials_decode(&credentials, ssid_hex, password_hex));
    password_hex[0] = '7';
    password_hex[1] = 'a'; /* 'z' is not a hexadecimal PSK digit. */
    assert(!micros_wifi_credentials_decode(&credentials, ssid_hex, password_hex));
    assert(!credentials.version &&
           !credentials.password_bytes); /* Failure erases partial secrets. */
    ssid_hex[64] = ssid_hex[65] = '6';
    ssid_hex[66] = 0;
    assert(!micros_wifi_credentials_decode(&credentials, ssid_hex, "-"));
    assert(micros_wifi_credentials_decode(&credentials, "74657374", "-"));
    credentials.version++;
    assert(!micros_wifi_credentials_valid(&credentials));
    micros_wifi_profiles_t profiles = {.version = MICROS_WIFI_PROFILES_VERSION};
    assert(micros_wifi_profiles_valid(&profiles));
    const char *names[] = {"61", "62", "63", "64", "65"};
    for (unsigned i = 0; i < MICROS_WIFI_PRIMARY_LIMIT; ++i) {
        assert(micros_wifi_credentials_decode(&credentials, names[i], "-"));
        assert(micros_wifi_profiles_put(&profiles, &credentials, 0));
    }
    assert(micros_wifi_credentials_decode(&credentials, names[4], "-"));
    micros_wifi_profiles_t previous = profiles;
    assert(!micros_wifi_profiles_put(&profiles, &credentials, 0));
    assert(!memcmp(&profiles, &previous, sizeof(profiles)));
    assert(micros_wifi_profiles_put(&profiles, &credentials, 1));
    assert(micros_wifi_profiles_valid(&profiles));
    assert(micros_wifi_credentials_decode(&credentials, names[1], "70617373776f7264"));
    assert(micros_wifi_profiles_put(&profiles, &credentials, 1)); /* Moves primary, replaces fallback. */
    assert(profiles.entries[1].ssid[0] == 'c' && !profiles.entries[3].ssid_bytes);
    assert(profiles.entries[4].ssid[0] == 'b');
    assert(micros_wifi_profiles_put(&profiles, &credentials, 0)); /* Promotes fallback, no duplicate. */
    assert(!profiles.entries[4].ssid_bytes && profiles.entries[3].ssid[0] == 'b');
    assert(micros_wifi_profiles_valid(&profiles));
    assert(micros_wifi_profiles_remove(&profiles, &credentials));
    assert(!micros_wifi_profiles_remove(&profiles, &credentials));
    previous = profiles;
    profiles.entries[4] = profiles.entries[0];
    assert(!micros_wifi_profiles_valid(&profiles));
    profiles = previous;
    profiles.entries[0].version = 0;
    assert(!micros_wifi_profiles_valid(&profiles));
    puts("PASS Wi-Fi credential bounds, hex parser, NVS version and failed-input clearing");
}
