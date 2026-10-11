/* Compile the real controller against a deterministic radio/NVS model. */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "wifi_credentials.h"
#define CONFIG_MICROS_REMOTE_ENABLED 1
#define ESP_OK 0
#define ESP_ERR_NVS_NOT_FOUND 1
#define NVS_READONLY 0
#define NVS_READWRITE 1
#define WIFI_EVENT 1
#define IP_EVENT 2
#define WIFI_EVENT_STA_DISCONNECTED 1
#define WIFI_EVENT_SCAN_DONE 2
#define IP_EVENT_STA_GOT_IP 3
#define ESP_EVENT_ANY_ID 0
#define WIFI_AUTH_OPEN 0
#define WIFI_AUTH_WPA2_PSK 2
#define WIFI_STORAGE_RAM 0
#define WIFI_MODE_STA 0
#define WIFI_IF_STA 0
#define WIFI_REASON_ASSOC_LEAVE 8
#define WIFI_REASON_NO_AP_FOUND 201
#define WIFI_REASON_AUTH_FAIL 202
#define WIFI_REASON_HANDSHAKE_TIMEOUT 204
#define WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT 15
#define IPSTR "%u"
#define IP2STR(ip) ((ip)->addr)
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(lock) ((void)(lock))
#define portEXIT_CRITICAL(lock) ((void)(lock))
#define ESP_ERROR_CHECK(call) assert((call) == ESP_OK)
#define WIFI_INIT_CONFIG_DEFAULT() {0}
typedef int esp_err_t, esp_event_base_t, portMUX_TYPE, nvs_handle_t, esp_netif_t;
typedef struct { unsigned addr; } esp_ip4_addr_t;
typedef struct { esp_ip4_addr_t ip; } esp_netif_ip_info_t;
typedef struct { unsigned reason; } wifi_event_sta_disconnected_t;
typedef struct { uint8_t ssid[33]; int rssi, authmode; } wifi_ap_record_t;
typedef struct { int unused; } wifi_init_config_t;
typedef struct { bool show_hidden; uint8_t *ssid; } wifi_scan_config_t;
typedef struct { struct { uint8_t ssid[32], password[64]; struct { int authmode; } threshold; } sta; } wifi_config_t;
static int64_t clock_us;
static int radio_visible, radio_associated, scan_calls, connect_calls, ready_calls, fail_storage;
static char scanned[33], attempted[33];
static micros_wifi_profiles_t disk_profiles;
static micros_wifi_credentials_t disk_legacy;
static int disk_has_profiles;
static int64_t esp_timer_get_time(void) { return clock_us; }
static int nvs_flash_init(void) { return 0; }
static int nvs_open(const char *ns, int mode, nvs_handle_t *h) { (void)ns; (void)mode; *h=1; return 0; }
static void nvs_close(nvs_handle_t h) { (void)h; }
static int nvs_commit(nvs_handle_t h) { (void)h; return 0; }
static int nvs_get_blob(nvs_handle_t h, const char *key, void *out, size_t *bytes) {
    (void)h;
    if (!strcmp(key,"profiles")) {
        if (!disk_has_profiles) return ESP_ERR_NVS_NOT_FOUND;
        assert(*bytes>=sizeof(disk_profiles)); memcpy(out,&disk_profiles,sizeof(disk_profiles));
        *bytes=sizeof(disk_profiles); return 0;
    }
    if (!disk_legacy.ssid_bytes) return ESP_ERR_NVS_NOT_FOUND;
    assert(*bytes>=sizeof(disk_legacy)); memcpy(out,&disk_legacy,sizeof(disk_legacy));
    *bytes=sizeof(disk_legacy); return 0;
}
static int nvs_set_blob(nvs_handle_t h,const char *key,const void *data,size_t bytes) {
    (void)h; assert(!strcmp(key,"profiles")); assert(bytes==sizeof(disk_profiles));
    if (fail_storage) return 2;
    memcpy(&disk_profiles,data,bytes); disk_has_profiles=1; return 0;
}
static int esp_netif_init(void) { return 0; }
static int esp_event_loop_create_default(void) { return 0; }
static esp_netif_t *esp_netif_create_default_wifi_sta(void) { static int n; return &n; }
static int esp_event_handler_register(int base,int event,void (*fn)(void *,int,int32_t,void *),void *arg) {
    (void)base;(void)event;(void)fn;(void)arg;return 0;
}
static int esp_wifi_init(wifi_init_config_t *c) { (void)c; return 0; }
static int esp_wifi_set_storage(int v) { (void)v; return 0; }
static int esp_wifi_set_mode(int v) { (void)v; return 0; }
static int esp_wifi_start(void) { return 0; }
static int esp_wifi_get_mac(int v,uint8_t *mac) { (void)v; memset(mac,0,6);return 0; }
static int esp_wifi_set_config(int v,wifi_config_t *c) {
    (void)v;memcpy(attempted,c->sta.ssid,32);attempted[32]=0;return 0;
}
static int esp_wifi_connect(void) { ++connect_calls;return 0; }
static int esp_wifi_disconnect(void) { radio_associated=0;return 0; }
static int esp_wifi_scan_start(wifi_scan_config_t *c,bool block) {
    (void)block;++scan_calls;snprintf(scanned,sizeof(scanned),"%s",c->ssid ? (char *)c->ssid : "");return 0;
}
static int esp_wifi_scan_stop(void) { return 0; }
static int esp_wifi_clear_ap_list(void) { return 0; }
static int esp_wifi_scan_get_ap_records(uint16_t *count,wifi_ap_record_t *records) {
    *count=radio_visible ? 1 : 0;
    if (*count) { memset(records,0,sizeof(*records)); memcpy(records->ssid,scanned,33); }
    return 0;
}
static int esp_wifi_sta_get_ap_info(wifi_ap_record_t *ap) {
    if (!radio_associated) return 1;
    memset(ap,0,sizeof(*ap));memcpy(ap->ssid,attempted,33);return 0;
}
static int esp_netif_get_ip_info(esp_netif_t *n,esp_netif_ip_info_t *ip) { (void)n;ip->ip.addr=123;return 0; }
#include "../../src/firmware/platforms/esp32/src/network.c"
static void ready(void) { ++ready_calls; }
static void advance(int64_t us) { clock_us+=us;micros_wifi_poll(); }
static void scan_done(int visible) {
    radio_visible=visible;wifi_event(NULL,WIFI_EVENT,WIFI_EVENT_SCAN_DONE,NULL);micros_wifi_poll();
}
static void command(const char *text) { char buffer[256];snprintf(buffer,sizeof(buffer),"%s",text);micros_wifi_command(buffer); }
int main(void) {
    assert(micros_wifi_credentials_decode(&disk_legacy,"686f6d65","70617373776f7264"));
    micros_wifi_start(ready); /* Existing single-network NVS migrates without losing credentials. */
    assert(has_saved && !memcmp(saved_profiles.entries[0].ssid,"home",4));
    command("WIFI ADD 6f6666696365 70617373776f7264");
    command("WIFI FALLBACK 70686f6e65 70617373776f7264");
    assert(connect_calls==0); /* Offline provisioning never needs the target nearby. */
    advance(WIFI_RETRY_US);assert(!strcmp(scanned,"home") && connect_calls==0);
    scan_done(0);advance(WIFI_RETRY_US);assert(!strcmp(scanned,"office") && connect_calls==0);
    scan_done(0);advance(WIFI_RETRY_US);assert(!strcmp(scanned,"phone") && connect_calls==0);
    scan_done(1);assert(connect_calls==1 && !strcmp(attempted,"phone"));
    radio_associated=1;wifi_event(NULL,IP_EVENT,IP_EVENT_STA_GOT_IP,NULL);micros_wifi_poll();
    assert(connected && ready_calls==1);
    int previous_scans=scan_calls;advance(WIFI_TRIAL_US*3);assert(scan_calls==previous_scans);
    command("WIFI SCAN");scan_done(1);assert(connected); /* Manual discovery keeps healthy connection. */
    wifi_event_sta_disconnected_t disconnected={WIFI_REASON_AUTH_FAIL};radio_associated=0;
    wifi_event(NULL,WIFI_EVENT,WIFI_EVENT_STA_DISCONNECTED,&disconnected);micros_wifi_poll();
    advance(WIFI_RETRY_US);assert(!strcmp(scanned,"home"));scan_done(1);assert(connect_calls==2);
    /* An available but unusable primary cannot trap the device forever at DHCP. */
    advance(WIFI_TRIAL_US);advance(WIFI_RETRY_US);assert(!strcmp(scanned,"office"));
    scan_done(1);wifi_event(NULL,WIFI_EVENT,WIFI_EVENT_STA_DISCONNECTED,&disconnected);micros_wifi_poll();
    advance(WIFI_RETRY_US);assert(!strcmp(scanned,"phone"));scan_done(0);
    advance(WIFI_RETRY_US);assert(!has_active);previous_scans=scan_calls;
    advance(WIFI_CYCLE_RETRY_US-1);assert(scan_calls==previous_scans);
    advance(1);assert(!strcmp(scanned,"home"));
    advance(WIFI_SCAN_TIMEOUT_US);assert(!scanning && !attempt_active);
    /* Writes fail atomically in memory; replacement never creates multiple fallbacks. */
    fail_storage=1;command("WIFI FALLBACK 6e6577 70617373776f7264");
    assert(!memcmp(saved_profiles.entries[4].ssid,"phone",5));fail_storage=0;
    command("WIFI FALLBACK 6e6577 70617373776f7264");assert(saved_profiles.entries[4].ssid_bytes==3);
    int before_trial = connect_calls;
    command("WIFI SET 616273656e74 70617373776f7264");
    advance(WIFI_RETRY_US);assert(!strcmp(scanned,"absent"));scan_done(0);
    assert(!testing && connect_calls==before_trial && !strcmp(outcome,"network_not_found"));
    assert(saved_profiles.entries[0].ssid_bytes==4); /* Failed trials preserve the list. */
    command("WIFI SET 747269616c 70617373776f7264");advance(WIFI_RETRY_US);scan_done(1);
    radio_associated=1;wifi_event(NULL,IP_EVENT,IP_EVENT_STA_GOT_IP,NULL);micros_wifi_poll();
    assert(!testing && connected && !strcmp(outcome,"saved"));
    assert(saved_profiles.entries[2].ssid_bytes==5 && saved_profiles.entries[4].ssid_bytes==3);
    command("WIFI FORGET 747269616c");assert(!connected && !attempt_active);
    command("WIFI FORGET 686f6d65");command("WIFI FORGET 6f6666696365");command("WIFI FORGET 6e6577");
    assert(!has_saved && disk_has_profiles);
    micros_wifi_start(ready);assert(!has_saved); /* Deleted legacy entry must not reappear. */
    /* Remote settings: preserve by SSID, atomic failures, no secret readback. */
    uint8_t wire[MICROS_WIFI_SETTINGS_BYTES] = {0};
    memcpy(wire, "MWF1", 4);
    wire[4]=4;wire[5]=8;wire[6]=2;
    memcpy(wire+8,"home",4);memcpy(wire+40,"password",8);
    wire[304]=5;wire[305]=8;wire[306]=2;
    memcpy(wire+308,"phone",5);memcpy(wire+340,"password",8);
    connected=1;radio_associated=1;
    assert(!micros_wifi_settings_write(wire,sizeof(wire)));
    assert(connected && radio_associated && saved_profiles.entries[4].ssid_bytes==5);
    char snapshot[1024];assert(micros_wifi_settings_read(snapshot,sizeof(snapshot)));
    assert(!strstr(snapshot,"password") && strstr(snapshot,"70686f6e65"));
    assert(!micros_wifi_settings_read(snapshot,10));
    micros_wifi_profiles_t before=saved_profiles;
    wire[5]=0;wire[6]=1;memset(wire+40,0,64);
    assert(!micros_wifi_settings_write(wire,sizeof(wire)));
    assert(!memcmp(&before,&saved_profiles,sizeof(before)));
    wire[7]=1;assert(micros_wifi_settings_write(wire,sizeof(wire))==1);wire[7]=0;
    assert(micros_wifi_settings_write(wire,sizeof(wire)-1)==1);
    memcpy(wire+104,wire+4,100); /* Duplicate primary. */
    assert(micros_wifi_settings_write(wire,sizeof(wire))==1);memset(wire+104,0,100);
    wire[8]='X';assert(micros_wifi_settings_write(wire,sizeof(wire))==1);wire[8]='h';
    wire[308]='X';fail_storage=1;
    assert(micros_wifi_settings_write(wire,sizeof(wire))==2);fail_storage=0;
    assert(!memcmp(&before,&saved_profiles,sizeof(before)));
    memcpy(wire+204,wire+4,100);memset(wire+4,0,100); /* Empty primary slots compact. */
    assert(!micros_wifi_settings_write(wire,sizeof(wire)));
    assert(saved_profiles.entries[0].ssid_bytes==4 && !saved_profiles.entries[1].ssid_bytes);
    scanning=1;assert(micros_wifi_settings_write(wire,sizeof(wire))==-1);scanning=0;
    memset(wire+4,0,sizeof(wire)-4);assert(micros_wifi_settings_write(wire,sizeof(wire))==1);
    puts("PASS availability-first selection, fallback, deadlines, sticky connection and persistence");
}
