#include <micros/network.h>
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "sdkconfig.h"
#include "wifi_credentials.h"
#include <stdio.h>
#include <string.h>
#if CONFIG_MICROS_REMOTE_ENABLED
/* One scan returns the twelve strongest entries to bound RAM and serial response size.
 * A 45-second trial covers association and DHCP; retries are spaced to avoid busy loops. */
#define WIFI_SCAN_LIMIT 12u
#define WIFI_TRIAL_US INT64_C(45000000)
#define WIFI_RETRY_US INT64_C(1000000)
#define WIFI_CYCLE_RETRY_US INT64_C(10000000)
#define WIFI_SCAN_TIMEOUT_US INT64_C(15000000)
#define EVENT_DISCONNECTED 1u
#define EVENT_GOT_IP 2u
#define EVENT_SCAN_DONE 4u
static portMUX_TYPE event_lock = portMUX_INITIALIZER_UNLOCKED;
static unsigned pending_events;
static unsigned disconnect_reason;
static unsigned disconnect_count, last_disconnect_reason;
static micros_wifi_profiles_t saved_profiles;
static micros_wifi_credentials_t active_credentials;
static unsigned candidate_cursor;
static int automatic_scan, attempt_active;
static char scan_ssid[MICROS_WIFI_SSID_BYTES + 1];
static int64_t attempt_deadline;
static int has_saved, has_active, connected, testing, scanning, initialized;
static int64_t trial_deadline, retry_deadline, scan_deadline;
static unsigned last_reason;
static const char *outcome = "idle";
static const char *scan_result = "idle";
static esp_netif_t *station_netif;
static esp_ip4_addr_t address;
static uint8_t station_mac[6]; /* IEEE 802 MAC address used to recognize a paired USB board. */
static wifi_ap_record_t networks[WIFI_SCAN_LIMIT];
static uint16_t network_count;
static void (*connection_ready)(void);

static void wifi_event(void *argument, esp_event_base_t base, int32_t event, void *data)
{
    (void)argument;
    /* Only copy event flags here. Configuration, NVS and TLS stay on the controller task. */
    portENTER_CRITICAL(&event_lock);
    if (base == WIFI_EVENT && event == WIFI_EVENT_STA_DISCONNECTED) {
        disconnect_reason = ((wifi_event_sta_disconnected_t *)data)->reason;
        last_disconnect_reason = disconnect_reason;
        ++disconnect_count;
        pending_events |= EVENT_DISCONNECTED;
    } else if (base == IP_EVENT && event == IP_EVENT_STA_GOT_IP)
        pending_events |= EVENT_GOT_IP;
    else if (base == WIFI_EVENT && event == WIFI_EVENT_SCAN_DONE)
        pending_events |= EVENT_SCAN_DONE;
    portEXIT_CRITICAL(&event_lock);
}
static int persist_profiles(const micros_wifi_profiles_t *profiles)
{
    nvs_handle_t storage;
    if (nvs_open("micros_wifi", NVS_READWRITE, &storage) != ESP_OK)
        return 0;
    esp_err_t result = nvs_set_blob(storage, "profiles", profiles, sizeof(*profiles));
    if (result == ESP_OK)
        result = nvs_commit(storage);
    nvs_close(storage);
    return result == ESP_OK;
}
static void refresh_saved(void)
{
    has_saved = 0;
    for (unsigned i = 0; i < MICROS_WIFI_PROFILE_COUNT; ++i)
        has_saved |= saved_profiles.entries[i].ssid_bytes != 0;
}
static int persist_credentials(void)
{
    micros_wifi_profiles_t proposed = saved_profiles;
    const micros_wifi_credentials_t *fallback = &proposed.entries[MICROS_WIFI_PRIMARY_LIMIT];
    int is_fallback = fallback->ssid_bytes == active_credentials.ssid_bytes &&
                     !memcmp(fallback->ssid, active_credentials.ssid, fallback->ssid_bytes);
    int okay = micros_wifi_profiles_put(&proposed, &active_credentials, is_fallback) &&
               persist_profiles(&proposed);
    if (okay) {
        saved_profiles = proposed;
        refresh_saved();
    }
    memset(&proposed, 0, sizeof(proposed));
    return okay;
}
static void begin_scan(int automatic)
{
    automatic_scan = automatic;
    scanning = 1;
    network_count = 0;
    scan_deadline = esp_timer_get_time() + WIFI_SCAN_TIMEOUT_US;
    wifi_scan_config_t configuration = {.show_hidden = true};
    if (automatic) {
        memcpy(scan_ssid, active_credentials.ssid, active_credentials.ssid_bytes);
        scan_ssid[active_credentials.ssid_bytes] = 0;
        configuration.ssid = (uint8_t *)scan_ssid;
    }
    if (esp_wifi_scan_start(&configuration, false) != ESP_OK) {
        scanning = 0;
        automatic_scan = 0;
        scan_result = "failed";
        retry_deadline = esp_timer_get_time() + WIFI_RETRY_US;
    }
}
static void connect_active(void)
{
    if (!has_active)
        return;
    wifi_config_t station = {0};
    memcpy(station.sta.ssid, active_credentials.ssid, active_credentials.ssid_bytes);
    memcpy(station.sta.password, active_credentials.password, active_credentials.password_bytes);
    station.sta.threshold.authmode =
        active_credentials.password_bytes ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;
    attempt_active = 1;
    attempt_deadline = esp_timer_get_time() + WIFI_TRIAL_US;
    if (esp_wifi_set_config(WIFI_IF_STA, &station) != ESP_OK || esp_wifi_connect() != ESP_OK) {
        attempt_active = 0;
        retry_deadline = esp_timer_get_time() + WIFI_RETRY_US;
    }
    /* Passwords are copied into the Wi-Fi driver; erase the controller's temporary copy. */
    memset(&station, 0, sizeof(station));
}
static void restore_saved(const char *result)
{
    testing = 0;
    outcome = result;
    connected = 0;
    address.addr = 0;
    esp_wifi_disconnect();
    memset(&active_credentials, 0, sizeof(active_credentials));
    has_active = 0;
    attempt_active = 0;
    candidate_cursor = 0;
    if (scanning) {
        esp_wifi_scan_stop();
        esp_wifi_clear_ap_list();
        scanning = automatic_scan = 0;
    }
    retry_deadline = esp_timer_get_time() + WIFI_RETRY_US;
}
void micros_wifi_start(void (*ready)(void))
{
    connection_ready = ready;
    ESP_ERROR_CHECK(
        nvs_flash_init()); /* Never erase unrelated NVS as an initialization fallback. */
    memset(&saved_profiles, 0, sizeof(saved_profiles));
    saved_profiles.version = MICROS_WIFI_PROFILES_VERSION;
    nvs_handle_t storage;
    if (nvs_open("micros_wifi", NVS_READONLY, &storage) == ESP_OK) {
        size_t bytes = sizeof(saved_profiles);
        esp_err_t loaded = nvs_get_blob(storage, "profiles", &saved_profiles, &bytes);
        if (loaded != ESP_OK || bytes != sizeof(saved_profiles) ||
            !micros_wifi_profiles_valid(&saved_profiles)) {
            memset(&saved_profiles, 0, sizeof(saved_profiles));
            saved_profiles.version = MICROS_WIFI_PROFILES_VERSION;
            /* Import legacy credentials only if the list has never been written.
             * An intentionally empty list must not resurrect a forgotten network. */
            if (loaded == ESP_ERR_NVS_NOT_FOUND) {
                micros_wifi_credentials_t legacy = {0};
                bytes = sizeof(legacy);
                if (nvs_get_blob(storage, "credentials", &legacy, &bytes) == ESP_OK &&
                    bytes == sizeof(legacy) && micros_wifi_credentials_valid(&legacy))
                    saved_profiles.entries[0] = legacy;
                memset(&legacy, 0, sizeof(legacy));
            }
        }
        nvs_close(storage);
    }
    refresh_saved();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    station_netif = esp_netif_create_default_wifi_sta();
    wifi_init_config_t configuration = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&configuration));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_get_mac(WIFI_IF_STA, station_mac));
    initialized = 1;
    has_active = 0;
    candidate_cursor = 0;
    retry_deadline = esp_timer_get_time() + WIFI_RETRY_US;
}
void micros_wifi_poll(void)
{
    if (!initialized)
        return;
    portENTER_CRITICAL(&event_lock);
    unsigned events = pending_events, reason = disconnect_reason;
    pending_events = 0;
    portEXIT_CRITICAL(&event_lock);
    int64_t now = esp_timer_get_time();
    if (events & EVENT_DISCONNECTED) {
        if (connected)
            candidate_cursor = 0;
        connected = 0;
        attempt_active = 0;
        address.addr = 0;
        /* A deliberate disconnect while switching/rolling back is not an authentication failure. */
        if (reason != WIFI_REASON_ASSOC_LEAVE &&
            (testing || (strcmp(outcome, "failed_timeout") && strcmp(outcome, "storage_error"))))
            last_reason = reason;
        retry_deadline = now + WIFI_RETRY_US;
    }
    if (events & EVENT_GOT_IP) {
        wifi_ap_record_t access_point;
        esp_netif_ip_info_t information;
        /* A queued DHCP event for the previous network must never commit trial credentials. */
        if (has_active && esp_wifi_sta_get_ap_info(&access_point) == ESP_OK &&
            strnlen((const char *)access_point.ssid, sizeof(access_point.ssid)) ==
                active_credentials.ssid_bytes &&
            !memcmp(access_point.ssid, active_credentials.ssid, active_credentials.ssid_bytes) &&
            esp_netif_get_ip_info(station_netif, &information) == ESP_OK && information.ip.addr) {
            connected = 1;
            attempt_active = 0;
            candidate_cursor = 0;
            address = information.ip;
            last_reason = 0;
            if (testing) {
                if (persist_credentials()) {
                    testing = 0;
                    outcome = "saved";
                } else
                    restore_saved("storage_error");
            }
            if (connected && connection_ready)
                connection_ready();
        }
    }
    if (scanning && (events & EVENT_SCAN_DONE)) {
        network_count = WIFI_SCAN_LIMIT;
        scan_result = esp_wifi_scan_get_ap_records(&network_count, networks) == ESP_OK ?
                      "ready" : "failed";
        scanning = 0;
        retry_deadline = now + WIFI_RETRY_US;
        if (automatic_scan) {
            automatic_scan = 0;
            int available = 0;
            if (!strcmp(scan_result, "ready"))
                for (unsigned i = 0; i < network_count; ++i)
                    if (strnlen((const char *)networks[i].ssid, sizeof(networks[i].ssid)) ==
                            active_credentials.ssid_bytes &&
                        !memcmp(networks[i].ssid, active_credentials.ssid, active_credentials.ssid_bytes))
                        available = 1;
            if (available)
                connect_active();
            else if (testing) {
                last_reason = WIFI_REASON_NO_AP_FOUND;
                restore_saved("network_not_found");
            }
        }
    }
    if (scanning && now >= scan_deadline) {
        esp_wifi_scan_stop();
        esp_wifi_clear_ap_list();
        scanning = automatic_scan = 0;
        scan_result = "timeout";
        network_count = 0;
        retry_deadline = now + WIFI_RETRY_US;
    }
    if (testing && now >= trial_deadline)
        restore_saved("failed_timeout");
    if (attempt_active && !connected && now >= attempt_deadline) {
        attempt_active = 0;
        esp_wifi_disconnect();
        retry_deadline = now + WIFI_RETRY_US;
    }
    if (!connected && !scanning && !attempt_active && now >= retry_deadline) {
        retry_deadline = INT64_MAX;
        if (testing) {
            begin_scan(1);
        } else {
            while (candidate_cursor < MICROS_WIFI_PROFILE_COUNT &&
                   !saved_profiles.entries[candidate_cursor].ssid_bytes)
                ++candidate_cursor;
            if (candidate_cursor < MICROS_WIFI_PROFILE_COUNT) {
                active_credentials = saved_profiles.entries[candidate_cursor++];
                has_active = 1;
                begin_scan(1);
            } else {
                candidate_cursor = 0;
                has_active = 0;
                memset(&active_credentials, 0, sizeof(active_credentials));
                retry_deadline = now + WIFI_CYCLE_RETRY_US;
            }
        }
    }
}
static void encode_ssid(char output[MICROS_WIFI_SSID_BYTES * 2 + 1], const uint8_t *ssid,
                        size_t bytes)
{
    static const char digits[] = "0123456789abcdef";
    for (size_t index = 0; index < bytes; ++index) {
        output[index * 2] = digits[ssid[index] >> 4];
        output[index * 2 + 1] = digits[ssid[index] & 15];
    }
    output[bytes * 2] = 0;
}
static const char *reason_name(void)
{
    if (!last_reason && connected)
        return "none";
    switch (last_reason) {
    case WIFI_REASON_NO_AP_FOUND:
        return "network_not_found";
    case WIFI_REASON_AUTH_FAIL:
    case WIFI_REASON_HANDSHAKE_TIMEOUT:
    case WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT:
        return "authentication_failed";
    default:
        return "connection_pending";
    }
}
static void print_status(void)
{
    /* Twelve records of at most 112 bytes plus connection metadata fit in 2 KiB.
     * Use the same stdout lock as application logs so they cannot split the JSON. */
    char response[2048], ssid_hex[MICROS_WIFI_SSID_BYTES * 2 + 1];
    wifi_ap_record_t access_point;
    const char *state = connected ? "connected" : (has_active || has_saved) ? "connecting" : "unconfigured";
    if (has_active && !connected && esp_wifi_sta_get_ap_info(&access_point) == ESP_OK)
        state = "waiting_for_ip";
    encode_ssid(ssid_hex, active_credentials.ssid, has_active ? active_credentials.ssid_bytes : 0);
    int bytes =
        snprintf(response, sizeof(response),
                 "WIFI "
                 "{\"mac\":\"%02x:%02x:%02x:%02x:%02x:%02x\",\"state\":\"%s\",\"saved\":%s,"
                 "\"testing\":%s,\"result\":\"%s\","
                 "\"reason\":\"%s\",\"reason_code\":%u,\"ip\":\"" IPSTR "\",\"ssid_hex\":\"%s\","
                 "\"scan\":\"%s\",\"networks\":[",
                 station_mac[0], station_mac[1], station_mac[2], station_mac[3], station_mac[4],
                 station_mac[5], state, has_saved ? "true" : "false", testing ? "true" : "false",
                 outcome, reason_name(), last_reason, IP2STR(&address), ssid_hex,
                 scanning ? "scanning" : scan_result);
    if (bytes < 0 || (size_t)bytes >= sizeof(response))
        return;
    size_t used = (size_t)bytes;
    for (uint16_t index = 0; index < network_count; ++index) {
        encode_ssid(ssid_hex, networks[index].ssid,
                    strnlen((const char *)networks[index].ssid, MICROS_WIFI_SSID_BYTES));
        bytes = snprintf(response + used, sizeof(response) - used,
                         "%s{\"ssid_hex\":\"%s\",\"rssi\":%d,\"open\":%s}", index ? "," : "",
                         ssid_hex, networks[index].rssi,
                         networks[index].authmode == WIFI_AUTH_OPEN ? "true" : "false");
        if (bytes < 0 || (size_t)bytes >= sizeof(response) - used)
            return;
        used += (size_t)bytes;
    }
    if (used + 3 <= sizeof(response)) {
        memcpy(response + used, "]}\n", 3);
        fwrite(response, 1, used + 3, stdout);
        fflush(stdout);
    }
}
static void print_profiles(void)
{
    char response[768], ssid_hex[MICROS_WIFI_SSID_BYTES * 2 + 1];
    size_t used = (size_t)snprintf(response, sizeof(response), "WIFI {\"saved_networks\":[");
    unsigned count = 0;
    for (unsigned i = 0; i < MICROS_WIFI_PROFILE_COUNT; ++i) {
        const micros_wifi_credentials_t *entry = &saved_profiles.entries[i];
        if (!entry->ssid_bytes)
            continue;
        encode_ssid(ssid_hex, entry->ssid, entry->ssid_bytes);
        int bytes = snprintf(response + used, sizeof(response) - used,
                             "%s{\"ssid_hex\":\"%s\",\"fallback\":%s}",
                             count++ ? "," : "", ssid_hex,
                             i == MICROS_WIFI_PRIMARY_LIMIT ? "true" : "false");
        if (bytes < 0 || (size_t)bytes >= sizeof(response) - used)
            return;
        used += (size_t)bytes;
    }
    if (used + 3 <= sizeof(response)) {
        memcpy(response + used, "]}\n", 3);
        fwrite(response, 1, used + 3, stdout);
        fflush(stdout);
    }
}
void micros_wifi_command(char *command)
{
    if (!initialized) {
        printf("WIFI {\"error\":\"Wi-Fi unavailable in this base\"}\n");
        return;
    }
    if (!strcmp(command, "WIFI STATUS")) {
        print_status();
        return;
    }
    if (!strcmp(command, "WIFI LIST")) {
        print_profiles();
        return;
    }
    if (!strcmp(command, "WIFI CANCEL")) {
        if (testing)
            restore_saved("cancelled");
        print_status();
        return;
    }
    if (testing || scanning) {
        printf("WIFI {\"error\":\"Wi-Fi operation already in progress\"}\n");
        return;
    }
    if (!strncmp(command, "WIFI ADD ", 9) || !strncmp(command, "WIFI FALLBACK ", 14) ||
        !strncmp(command, "WIFI FORGET ", 12)) {
        int fallback = !strncmp(command, "WIFI FALLBACK ", 14);
        int forget = !strncmp(command, "WIFI FORGET ", 12);
        char *ssid_hex = command + (fallback ? 14 : forget ? 12 : 9);
        char *password_hex = forget ? NULL : strchr(ssid_hex, ' ');
        if (!forget && !password_hex) {
            printf("WIFI {\"error\":\"Expected SSID and password fields\"}\n");
            return;
        }
        if (password_hex)
            *password_hex++ = 0;
        micros_wifi_credentials_t entry;
        if (!micros_wifi_credentials_decode(&entry, ssid_hex, forget ? "-" : password_hex)) {
            printf("WIFI {\"error\":\"Invalid SSID or password length/encoding\"}\n");
            return;
        }
        micros_wifi_profiles_t proposed = saved_profiles;
        int okay = forget ? micros_wifi_profiles_remove(&proposed, &entry) :
                            micros_wifi_profiles_put(&proposed, &entry, fallback);
        if (!okay) {
            printf("WIFI {\"error\":\"Network absent or four primary slots already occupied\"}\n");
        } else if (!persist_profiles(&proposed)) {
            printf("WIFI {\"error\":\"Could not save network list\"}\n");
        } else {
            saved_profiles = proposed;
            refresh_saved();
            candidate_cursor = 0;
            if (forget && active_credentials.ssid_bytes == entry.ssid_bytes &&
                !memcmp(active_credentials.ssid, entry.ssid, entry.ssid_bytes))
                restore_saved("forgotten");
            if (!connected && !attempt_active)
                retry_deadline = esp_timer_get_time() + WIFI_RETRY_US;
            print_profiles();
        }
        memset(&entry, 0, sizeof(entry));
        memset(&proposed, 0, sizeof(proposed));
        return;
    }
    if (!strcmp(command, "WIFI SCAN")) {
        begin_scan(0);
        print_status();
        return;
    }
    if (!strncmp(command, "WIFI SET ", 9)) {
        char *ssid_hex = command + 9;
        char *password_hex = strchr(ssid_hex, ' ');
        micros_wifi_credentials_t proposed;
        if (!password_hex) {
            printf("WIFI {\"error\":\"Expected SSID and password fields\"}\n");
            return;
        }
        *password_hex++ = 0;
        if (!micros_wifi_credentials_decode(&proposed, ssid_hex, password_hex)) {
            printf("WIFI {\"error\":\"Invalid SSID or password length/encoding\"}\n");
            return;
        }
        active_credentials = proposed;
        memset(&proposed, 0, sizeof(proposed));
        has_active = 1;
        testing = 1;
        attempt_active = 0;
        outcome = "testing";
        last_reason = 0;
        connected = 0;
        address.addr = 0;
        trial_deadline = esp_timer_get_time() + WIFI_TRIAL_US;
        esp_wifi_disconnect();
        retry_deadline = esp_timer_get_time() + WIFI_RETRY_US;
        print_status();
        return;
    }
    printf("WIFI {\"error\":\"Unknown Wi-Fi command\"}\n");
}

size_t micros_wifi_settings_read(char *output, size_t capacity)
{
    size_t used = (size_t)snprintf(output, capacity, "{\"networks\":[");
    unsigned count = 0;
    for (unsigned i = 0; i < MICROS_WIFI_PROFILE_COUNT; ++i) {
        const micros_wifi_credentials_t *entry = &saved_profiles.entries[i];
        if (!entry->ssid_bytes) continue;
        char hex[65];
        for (unsigned j = 0; j < entry->ssid_bytes; ++j)
            snprintf(hex + 2*j, 3, "%02x", entry->ssid[j]);
        if (used >= capacity) return 0;
        used += (size_t)snprintf(output + used, capacity - used,
            "%s{\"ssid_hex\":\"%s\",\"fallback\":%s,\"secured\":%s}",
            count++ ? "," : "", hex, i == MICROS_WIFI_PRIMARY_LIMIT ? "true" : "false",
            entry->password_bytes ? "true" : "false");
    }
    if (used >= capacity) return 0;
    int end = snprintf(output + used, capacity - used, "]}");
    return end >= 0 && (size_t)end < capacity - used ? used + (size_t)end : 0;
}

/* MWF1 + four 100-byte records: SSID length, password length, mode,
 * reserved byte, SSID[32], password[64]. Mode 0 empty, 1 preserve by SSID,
 * 2 replace (zero-length password explicitly selects an open network).
 * Build and validate the entire replacement before one NVS commit. */
int micros_wifi_settings_write(const uint8_t *body, size_t bytes)
{
    if (!initialized || testing || scanning) return -1;
    if (bytes != MICROS_WIFI_SETTINGS_BYTES || !body || memcmp(body, "MWF1", 4)) return 1;
    micros_wifi_profiles_t proposed = {.version = MICROS_WIFI_PROFILES_VERSION};
    int result = 1;
    unsigned count = 0, primary = 0;
    for (unsigned i = 0; i < 4; ++i) {
        const uint8_t *record = body + 4 + i*100;
        unsigned ssid_bytes = record[0], password_bytes = record[1], mode = record[2];
        if (record[3] || ssid_bytes > 32 || password_bytes > 64 || mode > 2) goto done;
        if (!mode) {
            for (unsigned j = 0; j < 100; ++j) if (record[j]) goto done;
            continue;
        }
        if (!ssid_bytes || (mode == 1 && password_bytes)) goto done;
        for (unsigned j = ssid_bytes; j < 32; ++j) if (record[4+j]) goto done;
        for (unsigned j = password_bytes; j < 64; ++j) if (record[36+j]) goto done;
        unsigned target = i == 3 ? MICROS_WIFI_PRIMARY_LIMIT : primary++;
        micros_wifi_credentials_t *entry = &proposed.entries[target];
        if (mode == 1) {
            for (unsigned j = 0; j < MICROS_WIFI_PROFILE_COUNT; ++j)
                if (saved_profiles.entries[j].ssid_bytes == ssid_bytes &&
                    !memcmp(saved_profiles.entries[j].ssid, record+4, ssid_bytes)) {
                    *entry = saved_profiles.entries[j]; break;
                }
            if (!entry->ssid_bytes) goto done;
        } else {
            entry->version = MICROS_WIFI_CREDENTIALS_VERSION;
            entry->ssid_bytes = ssid_bytes; entry->password_bytes = password_bytes;
            memcpy(entry->ssid, record+4, ssid_bytes);
            memcpy(entry->password, record+36, password_bytes);
        }
        if (!micros_wifi_credentials_valid(entry)) goto done;
        for (unsigned j = 0; j < target; ++j)
            if (proposed.entries[j].ssid_bytes == ssid_bytes &&
                !memcmp(proposed.entries[j].ssid, entry->ssid, ssid_bytes)) goto done;
        ++count;
    }
    if (!count || !micros_wifi_profiles_valid(&proposed)) goto done;
    if (!persist_profiles(&proposed)) { result = 2; goto done; }
    saved_profiles = proposed;
    refresh_saved();
    candidate_cursor = 0;
    if (!connected && !attempt_active) retry_deadline = esp_timer_get_time() + WIFI_RETRY_US;
    result = 0;
done:
    /* Volatile stores prevent dead-store removal of the local secret copy. */
    for (volatile uint8_t *p = (volatile uint8_t *)&proposed;
         p < (volatile uint8_t *)&proposed + sizeof(proposed); ++p) *p = 0;
    return result;
}

size_t micros_wifi_insights(char *output, size_t capacity)
{
    unsigned count, reason;
    portENTER_CRITICAL(&event_lock);
    count=disconnect_count; reason=last_disconnect_reason;
    portEXIT_CRITICAL(&event_lock);
    wifi_ap_record_t access_point;
    int available=connected && esp_wifi_sta_get_ap_info(&access_point)==ESP_OK;
    char signal[16]="null"; /* RSSI is signed dBm; null means no current association. */
    if (available) snprintf(signal, sizeof(signal), "%d", access_point.rssi);
    int written=snprintf(output,capacity,
        "{\"profiles_api\":1,\"connected\":%s,\"ip\":\"" IPSTR "\",\"rssi_dbm\":%s,\"disconnects\":%u,\"last_disconnect_reason\":%u}",
        connected ? "true":"false", IP2STR(&address),signal,count,reason);
    return written>=0 && (size_t)written<capacity ? (size_t)written : 0;
}

void micros_platform_network_snapshot(micros_network_snapshot_t *out) {
    *out=(micros_network_snapshot_t){0};
    out->connected=connected;out->configured=has_saved;out->profile_index=-1;
    out->disconnects=disconnect_count;out->disconnect_reason=last_disconnect_reason;
    wifi_ap_record_t ap;out->rssi_known=connected && esp_wifi_sta_get_ap_info(&ap)==ESP_OK;
    if(out->rssi_known)out->rssi_dbm=ap.rssi;
}

#else
void micros_wifi_start(void (*ready)(void)) { (void)ready; }
void micros_wifi_poll(void) {}
void micros_wifi_command(char *command)
{
    (void)command;
    printf("WIFI {\"error\":\"Wi-Fi is disabled in this base\"}\n");
}
size_t micros_wifi_settings_read(char *output, size_t capacity) { (void)output; (void)capacity; return 0; }
int micros_wifi_settings_write(const uint8_t *body, size_t bytes) { (void)body; (void)bytes; return -1; }
size_t micros_wifi_insights(char *output, size_t capacity)
{
    int size = snprintf(output, capacity, "{\"enabled\":false}");
    return size < 0 || (size_t)size >= capacity ? 0 : (size_t)size;
}

void micros_platform_network_snapshot(micros_network_snapshot_t *out) { *out=(micros_network_snapshot_t){0};out->profile_index=-1; }

#endif
int micros_network_fetch_base(const char session[33],const char digest[65]) { (void)session;(void)digest;return 0; }
int micros_network_fetch_busy(void) { return 0; }
int micros_network_configure_relay(const char *host,unsigned port,const char *token) { (void)host;(void)port;(void)token;return -4; }
