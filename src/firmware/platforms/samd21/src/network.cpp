#include "device_support.h"
#include <micros/network.h>
#include "network_support.h"
#include "update_support.h"
#include "FreeRTOS.h"
#include "support/http.h"
#include "semphr.h"
#include "task.h"
#include <WiFiNINA.h>
#include <string.h>
extern "C"
{
#include "support/hardware.h"
#include "image.h"
#include "support/storage.h"
}
// Two separately erased settings records, committed only after all data pages.
struct Settings
{
    uint32_t magic, sequence;
    char ssid[33], password[65], host[128], token[65];
    uint8_t pad[1];
    uint32_t port, crc;
    // Optional extension: the original CRC/layout remains readable by older bases.
    char second_ssid[33], second_password[65];
    uint8_t second_pad[2];
    uint32_t second_crc;
};
static_assert(sizeof(Settings)<=448 && offsetof(Settings,crc)==304, "Saved-settings compatibility");
static Settings settings;
static int settings_sector = -1;
static uint32_t boot_sequence;
static volatile bool reconnect;
static volatile bool reboot_after_reply;
void embedded_network_reboot_after_reply(void) { reboot_after_reply = true; }
static char fetch_actor[33], fetch_hash[65];
static volatile bool fetch_pending;
bool embedded_network_base_fetching(void) { return fetch_pending; }
bool embedded_network_base_fetch(const char *actor, const char *hash) {
    if(fetch_pending || strlen(actor)!=32 || strlen(hash)!=64) return false;
    strcpy(fetch_actor,actor);strcpy(fetch_hash,hash);fetch_pending=true;return true;
}
static char mac[13] = "000000000000", ip[16] = "0.0.0.0", firmware[16];
static int connected, last_http, active_profile = -1;
static int32_t signal_dbm;
static uint32_t disconnects;
static const char *network_stage = "idle";
static TaskHandle_t worker;
static SemaphoreHandle_t request_ready, response_ready;
static char request_text[600];
static char *response_text;
static uint8_t wire[664];
static unsigned response_bytes;
static const uint32_t SETTINGS_BASE = 0x3c00;
static bool valid(const Settings &value)
{
    return value.magic == 0x3257464d && value.sequence &&
           memchr(value.ssid, 0, sizeof(value.ssid)) &&
           memchr(value.password, 0, sizeof(value.password)) &&
           memchr(value.host, 0, sizeof(value.host)) &&
           memchr(value.token, 0, sizeof(value.token)) && value.port <= 65535 &&
           value.crc == micros_crc32((const uint8_t *)&value, offsetof(Settings, crc));
}
static bool save(Settings &next, bool reconnect_now = true)
{
    if (settings.sequence == UINT32_MAX)
        return false;
    next.magic = 0x3257464d;
    next.sequence = settings.sequence + 1;
    next.second_crc = micros_crc32((const uint8_t *)next.second_ssid, 100);
    next.crc = micros_crc32((const uint8_t *)&next, offsetof(Settings, crc));
    uint8_t data[512];
    memset(data, 255, sizeof(data));
    memcpy(data, &next, sizeof(next));
    // The commit page is outside the struct, after its checksum.
    uint32_t commit = 0x54494d43;
    memcpy(data + 448, &commit, 4);
    unsigned sector = settings_sector == 0 ? 1 : 0;
    uint32_t address = SETTINGS_BASE + sector * 512;
    if (!embedded_flash_erase(address, 512) || !embedded_flash_write(address, data, 448) ||
        !embedded_flash_write(address + 448, data + 448, 64))
        return false;
    taskENTER_CRITICAL();
    if(active_profile>=0) {
        const char *ssid=active_profile?settings.second_ssid:settings.ssid;
        active_profile=!strcmp(ssid,next.ssid)?0:(!strcmp(ssid,next.second_ssid)?1:-1);
    }
    settings = next;
    settings_sector = sector;
    if (reconnect_now) reconnect = true;
    taskEXIT_CRITICAL();
    return true;
}
void micros_platform_network_snapshot(micros_network_snapshot_t *snapshot)
{
    *snapshot = {};
    snapshot->connected = connected;
    snapshot->configured = settings.ssid[0] != 0;
    snapshot->relay_configured = settings.host[0] != 0;
    snapshot->stack_free = worker ? uxTaskGetStackHighWaterMark(worker) * sizeof(StackType_t) : 0;
    snapshot->stage = network_stage; snapshot->firmware = firmware;
    snapshot->rssi_known = connected; snapshot->rssi_dbm = signal_dbm;
    snapshot->relay_http = last_http; snapshot->mac = mac; snapshot->ip = ip;
    snapshot->profile_index = connected ? active_profile : -1;
    snapshot->disconnects = disconnects;
}
bool embedded_network_online(void) {return connected && (last_http==200 || last_http==204);}
void embedded_network_identity(MicrosPrint &out) { out.print(mac); }
bool embedded_network_configure(const char *ssid, const char *password)
{
    if (!ssid || !password || !ssid[0] || strlen(ssid) > 32 || strlen(password) > 64)
        return false;
    Settings next = settings;
    strcpy(next.ssid, ssid);
    strcpy(next.password, password);
    return save(next);
}
void embedded_network_profiles(MicrosPrint &out)
{
    out.print("{\"result\":0,\"networks\":[");
    for(unsigned i=0;i<2;++i) {
        const char *ssid=i?settings.second_ssid:settings.ssid;
        const char *password=i?settings.second_password:settings.password;
        if(!ssid[0])continue;
        if(i && settings.ssid[0])out.print(',');
        out.print("{\"ssid_hex\":\"");
        const char *hex="0123456789abcdef";
        for(const unsigned char *p=(const unsigned char *)ssid;*p;++p) {
            out.write(hex[*p>>4]);out.write(hex[*p&15]);
        }
        out.print("\",\"fallback\":");out.print(i?"true":"false");
        out.print(",\"secured\":");out.print(password[0]?"true":"false");out.print('}');
    }
    out.println("]}");
}
static bool profile(Settings &next,unsigned index,const char *ssid,const char *password) {
    if(!ssid || strlen(ssid)>32 || (!index && !ssid[0]))return false;
    char *target=index?next.second_ssid:next.ssid;
    char *secret=index?next.second_password:next.password;
    if(!ssid[0]){target[0]=secret[0]=0;return true;}
    if(!password) {
        if(!strcmp(ssid,settings.ssid))password=settings.password;
        else if(!strcmp(ssid,settings.second_ssid))password=settings.second_password;
        else return false;
    }
    size_t n=strlen(password);
    if(n && (n<8 || n>64))return false;
    if(n==64)for(size_t i=0;i<n;++i)if(!isxdigit(password[i]))return false;
    strcpy(target,ssid);strcpy(secret,password);return true;
}
bool embedded_network_profiles_set(const char *ssid,const char *password,const char *second,const char *secret) {
    Settings next=settings;
    bool ok=profile(next,0,ssid,password) && profile(next,1,second,secret) &&
        (!next.second_ssid[0] || strcmp(next.ssid,next.second_ssid)) && save(next,false);
    memset(&next,0,sizeof(next));return ok;
}
bool embedded_network_profile(const char *ssid,const char *password) {
    return embedded_network_profiles_set(ssid,password,settings.second_ssid,NULL);
}
bool embedded_network_relay(const char *host, unsigned port, const char *token)
{
    if (!host || !host[0] || strlen(host) > 127 || !port || port > 65535 || !token ||
        strlen(token) != 64)
        return false;
    for (const char *p = host; *p; ++p)
        if (!isalnum(*p) && *p != '.' && *p != '-')
            return false;
    for (const char *p = token; *p; ++p)
        if (!isxdigit(*p))
            return false;
    Settings next = settings;
    strcpy(next.host, host);
    strcpy(next.token, token);
    next.port = port;
    return save(next);
}
static void release_response() { free(response_text);response_text=nullptr;response_bytes=0; }
void embedded_network_poll(char *(*execute)(char *)) {
 if (!request_ready || xSemaphoreTake(request_ready, 0) != pdTRUE) return;
 release_response();
 response_text=execute(request_text);
 response_bytes=response_text?strlen(response_text):0;
 memset(request_text,0,sizeof(request_text));
 xSemaphoreGive(response_ready);
}
static bool local_command(const char *command)
{
    if (strlen(command) >= sizeof(request_text))
        return false;
    strcpy(request_text, command);
    xSemaphoreGive(request_ready);
    // One worker owns this mailbox. A timed-out operation is never replayed.
    return xSemaphoreTake(response_ready, pdMS_TO_TICKS(12000)) == pdTRUE;
}
struct NetworkClock
{
    uint32_t now() { return millis(); }
    void idle() { vTaskDelay(1); }
};
static int exchange(const Settings &current, const char *path, const char *boot, int result_code,
                    size_t body_bytes, size_t &received)
{
    WiFiSSLClient client;
    client.setTimeout(8000);
    // TLS and hostname verification are delegated to the stock NINA firmware.
    // Its trust store must contain the server's CA; there is no insecure fallback.
    network_stage = "tls_connect";
    if (!client.connect(current.host, current.port))
        return -1;
    network_stage = "request";
    client.print("POST ");
    client.print(path);
    client.print(" HTTP/1.1\r\nHost: ");
    client.print(current.host);
    client.print("\r\nAuthorization: Bearer ");
    client.print(current.token);
    client.print("\r\nConnection: close\r\nAccept-Encoding: identity\r\nContent-Type: "
                 "application/octet-stream\r\nContent-Length: ");
    client.print(body_bytes);
    if (boot)
    {
        client.print("\r\nX-Micros-Boot: ");
        client.print(boot);
    }
    if (result_code)
    {
        client.print("\r\nX-Micros-Result: ");
        client.print(result_code);
    }
    client.print("\r\n\r\n");
    if (client.write((const uint8_t *)response_text, body_bytes) != body_bytes)
    {
        client.stop();
        return -1;
    }
    network_stage = "headers";
    NetworkClock clock;
    micros_samd21::HttpReader<WiFiSSLClient, NetworkClock> reader(client, clock);
    int result = reader.response(wire, sizeof(wire), received);
    client.stop();
    if (result >= 200)
        network_stage = "idle";
    return result;
}
static bool download_base(const Settings &current)
{
    WiFiSSLClient client;
    client.setTimeout(8000);
    network_stage = "base_download";
    if (!client.connect(current.host, current.port)) return false;
    client.print("GET /agent/"); client.print(mac); client.print("/base/"); client.print(fetch_hash);
    client.print(" HTTP/1.1\r\nHost: "); client.print(current.host);
    client.print("\r\nAuthorization: Bearer "); client.print(current.token);
    client.print("\r\nConnection: close\r\nAccept-Encoding: identity\r\n\r\n");
    NetworkClock clock;
    micros_samd21::HttpReader<WiFiSSLClient, NetworkClock> reader(client, clock, 90000);
    bool ok = reader.download(wire, 81920, embedded_base_ota_write);
    client.stop();
    return ok;
}
static void network_worker(void *)
{
    WiFi.setTimeout(1500);
    // Yield busy Arduino delays to the scheduler; only this worker touches SPI/NINA.
    strncpy(firmware, WiFi.firmwareVersion(), sizeof(firmware) - 1);
    uint8_t address[6];
    WiFi.macAddress(address);
    snprintf(mac, sizeof(mac), "%02x%02x%02x%02x%02x%02x", address[0], address[1], address[2],
             address[3], address[4], address[5]);
    char boot[17], path[112], command_id[33] = {0};
    uint64_t nonce = boot_sequence;
    snprintf(boot, sizeof(boot), "%08lx%08lx", (unsigned long)(nonce >> 32), (unsigned long)nonce);
    int pending_result = 0;
    unsigned next_profile = 0;
    for (;;)
    {
        Settings current;
        taskENTER_CRITICAL();
        current = settings;
        bool reset = reconnect;
        reconnect = false;
        taskEXIT_CRITICAL();
        if (reset)
        {
            WiFi.disconnect();
            if (connected) ++disconnects;
            connected = 0;
            next_profile = 0;
        }
        if (!current.ssid[0])
        {
            vTaskDelay(pdMS_TO_TICKS(1000));
            continue;
        }
        if (WiFi.status() != WL_CONNECTED)
        {
            if (connected) ++disconnects;
            connected = 0;
            const char *ssid=next_profile && current.second_ssid[0]?current.second_ssid:current.ssid;
            const char *password=next_profile && current.second_ssid[0]?current.second_password:current.password;
            if(password[0])WiFi.begin(ssid,password);else WiFi.begin(ssid);
            connected = WiFi.status() == WL_CONNECTED;
            if(connected) {
                taskENTER_CRITICAL();
                active_profile=!strcmp(ssid,settings.ssid)?0:(!strcmp(ssid,settings.second_ssid)?1:-1);
                taskEXIT_CRITICAL();
            }
            if (!connected)
            {
                next_profile ^= 1;
                vTaskDelay(pdMS_TO_TICKS(2000));
                continue;
            }
        }
        connected = 1;
        next_profile = 0;
        signal_dbm = WiFi.RSSI();
        IPAddress local = WiFi.localIP();
        snprintf(ip, sizeof(ip), "%u.%u.%u.%u", local[0], local[1], local[2], local[3]);
        if (!current.host[0])
        {
            vTaskDelay(pdMS_TO_TICKS(1000));
            continue;
        }
        size_t received = 0;
        if (pending_result)
        {
            snprintf(path, sizeof(path), "/agent/%s/result/%s", mac, command_id);
            last_http = exchange(current, path, NULL, 200, response_bytes, received);
            if (last_http != 200 && last_http != 400)
            {
                vTaskDelay(pdMS_TO_TICKS(2000));
                continue;
            }
            if (last_http == 200 && reboot_after_reply)
                embedded_reset();
            reboot_after_reply = false;
            pending_result = 0;
            release_response();
        }
        if (fetch_pending)
        {
            bool downloaded = download_base(current);
            fetch_pending = false;
            snprintf(path, sizeof(path), "RPC %u 0 0 0 %s -", downloaded ? 15u : 17u, fetch_actor);
            if (!local_command(path)) { vTaskDelete(NULL); return; }
            if (reboot_after_reply) embedded_reset();
            network_stage = downloaded ? "base_rejected" : "base_download_failed";
        }
        if (!local_command("RPC 0 0 0 0 - -"))
        {
            vTaskDelete(NULL);
            return;
        }
        snprintf(path, sizeof(path), "/agent/%s/poll", mac);
        last_http = exchange(current, path, boot, 0, response_bytes, received);
        release_response();
        if (last_http == 200 && received >= 64 && !memcmp(wire, "MRL1", 4))
        {
            uint32_t bytes;
            memcpy(&bytes, wire + 48, 4);
            if (bytes == received - 64 && bytes < sizeof(request_text) &&
                !memchr(wire + 64, 0, bytes))
            {
                static const char hex[] = "0123456789abcdef";
                for (unsigned i = 0; i < 16; ++i)
                {
                    command_id[i * 2] = hex[wire[4 + i] >> 4];
                    command_id[i * 2 + 1] = hex[wire[4 + i] & 15];
                }
                command_id[32] = 0;
                if (wire[20] == 18)
                {
                    memcpy(request_text, wire + 64, bytes);
                    request_text[bytes] = 0;
                }
                else if (wire[20] == 0)
                    strcpy(request_text, "RPC 0 0 0 0 - -");
                else if (wire[20] == 1)
                    strcpy(request_text, "RPC 1 0 0 0 - -");
                else
                    strcpy(request_text, "UNSUPPORTED");
                xSemaphoreGive(request_ready);
                if (xSemaphoreTake(response_ready, pdMS_TO_TICKS(12000)) != pdTRUE)
                {
                    vTaskDelete(NULL);
                    return;
                }
                pending_result = 1;
            }
        }
        memset(wire, 0, sizeof(wire));
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}
void embedded_network_start(void)
{
    for (unsigned i = 0; i < 2; ++i)
    {
        const Settings *record = (const Settings *)(uintptr_t)(SETTINGS_BASE + i * 512);
        const uint32_t *commit = (const uint32_t *)(uintptr_t)(SETTINGS_BASE + i * 512 + 448);
        if (*commit == 0x54494d43 && valid(*record) && record->sequence > settings.sequence)
        {
            settings = *record;
            if(settings.second_crc != micros_crc32((const uint8_t *)settings.second_ssid,100) ||
               !memchr(settings.second_ssid,0,33) || !memchr(settings.second_password,0,65)) {
                memset(settings.second_ssid,0,100);settings.second_crc=0;
            }
            settings_sector = i;
        }
    }
    // Persist boot identity before dispatching relay mutations; never sample user GPIO.
    if (!save(settings))
        return;
    boot_sequence = settings.sequence;
    request_ready = xSemaphoreCreateBinary();
    response_ready = xSemaphoreCreateBinary();
    if (request_ready && response_ready)
        xTaskCreate(network_worker, "nina", 640, NULL, 0, &worker);
}

#include <micros/transport.h>

#include <micros/network.h>
#include <micros/network_status.h>
#include "support/buffer_print.h"
extern "C" void embedded_network_identity_bytes(uint8_t identity[6]) {
 char text[32];MicrosBufferPrint out(text,sizeof(text));embedded_network_identity(out);
 for(unsigned i=0;i<6;++i){unsigned value=0;sscanf(text+2*i,"%2x",&value);identity[i]=(uint8_t)value;}
}
extern "C" void micros_wifi_start(void (*ready)(void)) { embedded_network_start();if(ready)ready(); }
extern "C" void micros_wifi_poll(void) {}
extern "C" size_t micros_wifi_insights(char *out,size_t capacity) {
 micros_network_snapshot_t snapshot;micros_platform_network_snapshot(&snapshot);
 return micros_network_status_json(out,capacity,&snapshot);
}
extern "C" size_t micros_wifi_settings_read(char *out,size_t capacity) {
 MicrosBufferPrint writer(out,capacity);embedded_network_profiles(writer);return writer.size();
}
extern "C" int micros_wifi_settings_write(const uint8_t *body,size_t bytes) {
 if(!body || bytes!=404 || memcmp(body,"MWF1",4))return -1;
 char names[2][33]={},secrets[2][65]={};bool keep[2]={};unsigned count=0;
 for(unsigned i=0;i<4;++i) {
  const uint8_t *record=body+4+i*100;unsigned sn=record[0],pn=record[1],mode=record[2];
  if(record[3] || sn>32 || pn>64 || mode>2)return -1;
  if(!mode){for(unsigned j=0;j<100;++j)if(record[j])return -1;continue;}
  if(count==2 || !sn || (mode==1 && pn) || memchr(record+4,0,sn) || memchr(record+36,0,pn))return -1;
  for(unsigned j=sn;j<32;++j)if(record[4+j])return -1;
  for(unsigned j=pn;j<64;++j)if(record[36+j])return -1;
  memcpy(names[count],record+4,sn);memcpy(secrets[count],record+36,pn);keep[count]=mode==1;++count;
 }
 int result=count && embedded_network_profiles_set(names[0],keep[0]?nullptr:secrets[0],names[1],keep[1]?nullptr:secrets[1])?0:-1;
 memset(secrets,0,sizeof(secrets));return result;
}
extern "C" void micros_wifi_command(char *command) {
 (void)command;char out[512];size_t bytes=micros_wifi_insights(out,sizeof(out));
 micros_transport_write(out,bytes);micros_transport_write("\n",1);
}

extern "C" int micros_network_fetch_base(const char session[33],const char digest[65]) { return embedded_network_base_fetch(session,digest); }
extern "C" int micros_network_fetch_busy(void) { return embedded_network_base_fetching(); }
extern "C" int micros_network_configure_relay(const char *host,unsigned port,const char *token) { return embedded_network_relay(host,port,token)?0:-1; }
