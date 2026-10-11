#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "support/storage.h"
#include "device_support.h"
#include <micros/network.h>
#include "esp_event_loop.h"
#include "esp_http_client.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/semphr.h"
#include "lwip/apps/sntp.h"
#include "nvs.h"
#include "tcpip_adapter.h"
#include <ctype.h>
#include <time.h>
// Private downloader query, not part of the shared controller contract.
unsigned embedded_base_ota_size();
struct Settings {
  char ssid[2][33], password[2][65], host[128], token[65];
  uint32_t port;
};
static Settings settings;
static volatile bool connected, reconnect, reboot_after_reply, fetch_pending;
static unsigned profile, disconnects;
static int active_profile = -1, last_http, last_disconnect_reason;
static char mac[13], ip[16], fetch_actor[33], fetch_hash[65];
static const char *stage = "starting";
static TaskHandle_t worker;
static SemaphoreHandle_t request_ready, response_ready;
static char request_text[600];
static char *response_text;
static uint8_t wire[664];
static unsigned response_bytes;
static esp_http_client_handle_t connection;
static void disconnect_tls() {
  if (connection)
    esp_http_client_cleanup(connection);
  connection = NULL;
}
static void restart() {
  disconnect_tls();
  esp_wifi_stop();
  vTaskDelay(pdMS_TO_TICKS(100));
  embedded_reset();
}
extern const char ca_start[] asm("_binary_relay_roots_pem_start");
static bool save(const Settings &next, bool immediate) {
  nvs_handle h;
  if (nvs_open("micros_wifi", NVS_READWRITE, &h) != ESP_OK)
    return false;
  bool ok = nvs_set_blob(h, "settings", &next, sizeof(next)) == ESP_OK &&
            nvs_commit(h) == ESP_OK;
  nvs_close(h);
  if (ok) {
    taskENTER_CRITICAL();
    if (connected && active_profile >= 0) {
      const char *active = settings.ssid[active_profile];
      active_profile = !strcmp(active, next.ssid[0])   ? 0
                       : !strcmp(active, next.ssid[1]) ? 1
                                                       : -1;
    }
    settings = next;
    if (immediate)
      reconnect = true;
    taskEXIT_CRITICAL();
  }
  return ok;
}
static bool valid_secret(const char *p) {
  size_t n = strlen(p);
  if (!n)
    return true;
  if (n < 8 || n > 64)
    return false;
  if (n == 64)
    for (size_t i = 0; i < n; ++i)
      if (!isxdigit((unsigned char)p[i]))
        return false;
  return true;
}
bool embedded_network_profiles_set(const char *ssid, const char *password,
                                   const char *second, const char *secret) {
  Settings next = settings;
  const char *names[2] = {ssid, second}, *secrets[2] = {password, secret};
  for (unsigned i = 0; i < 2; ++i) {
    if (!names[i] || strlen(names[i]) > 32 || (!i && !names[i][0]))
      return false;
    if (!names[i][0]) {
      next.ssid[i][0] = next.password[i][0] = 0;
      continue;
    }
    const char *p = secrets[i];
    if (!p) {
      for (unsigned j = 0; j < 2; ++j)
        if (!strcmp(names[i], settings.ssid[j]))
          p = settings.password[j];
    }
    if (!p || !valid_secret(p))
      return false;
    strcpy(next.ssid[i], names[i]);
    strcpy(next.password[i], p);
  }
  if (next.ssid[1][0] && !strcmp(next.ssid[0], next.ssid[1]))
    return false;
  bool ok = save(next, false);
  memset(&next, 0, sizeof(next));
  return ok;
}
bool embedded_network_profile(const char *ssid, const char *password) {
  return embedded_network_profiles_set(ssid, password, settings.ssid[1], NULL);
}
bool embedded_network_configure(const char *ssid, const char *password) {
  bool ok = embedded_network_profile(ssid, password);
  if (ok)
    reconnect = true;
  return ok;
}
bool embedded_network_relay(const char *host, unsigned port,
                            const char *token) {
  if (!host || !*host || strlen(host) > 127 || !port || port > 65535 ||
      !token || strlen(token) != 64)
    return false;
  for (const char *p = host; *p; ++p)
    if (!isalnum((unsigned char)*p) && *p != '.' && *p != '-')
      return false;
  for (const char *p = token; *p; ++p)
    if (!isxdigit((unsigned char)*p))
      return false;
  Settings next = settings;
  strcpy(next.host, host);
  strcpy(next.token, token);
  next.port = port;
  return save(next, false);
}
void embedded_network_identity(MicrosPrint &out) { out.print(mac); }
void embedded_network_profiles(MicrosPrint &out) {
  out.print("{\"result\":0,\"networks\":[");
  for (unsigned i = 0; i < 2; ++i)
    if (settings.ssid[i][0]) {
      if (i)
        out.print(',');
      out.print("{\"ssid_hex\":\"");
      const char *hex = "0123456789abcdef";
      for (const unsigned char *p = (const unsigned char *)settings.ssid[i]; *p;
           ++p) {
        out.write(hex[*p >> 4]);
        out.write(hex[*p & 15]);
      }
      out.print("\",\"fallback\":");
      out.print(i ? "true" : "false");
      out.print(",\"secured\":");
      out.print(settings.password[i][0] ? "true" : "false");
      out.print('}');
    }
  out.println("]}");
}
void micros_platform_network_snapshot(micros_network_snapshot_t *snapshot)
{
    *snapshot = {};
    snapshot->connected = connected;
    snapshot->configured = settings.ssid[0][0] != 0;
    snapshot->relay_configured = settings.host[0] != 0;
    snapshot->stack_free = worker ? uxTaskGetStackHighWaterMark(worker) : 0;
    snapshot->stage = stage;
    wifi_ap_record_t ap = {};
    snapshot->rssi_known = connected && esp_wifi_sta_get_ap_info(&ap) == ESP_OK;
    snapshot->rssi_dbm = ap.rssi; snapshot->disconnect_reason = last_disconnect_reason;
    snapshot->relay_http = last_http; snapshot->mac = mac; snapshot->ip = ip;
    snapshot->profile_index = connected ? active_profile : -1;
    snapshot->disconnects = disconnects;
}
bool embedded_network_online() {
  return connected && (last_http == 200 || last_http == 204);
}
void embedded_network_reboot_after_reply() { reboot_after_reply = true; }
bool embedded_network_base_fetching() { return fetch_pending; }
bool embedded_network_base_fetch(const char *actor, const char *hash) {
  if (fetch_pending || strlen(actor) != 32 || strlen(hash) != 64)
    return false;
  strcpy(fetch_actor, actor);
  strcpy(fetch_hash, hash);
  fetch_pending = true;
  return true;
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
static bool command(const char *text) {
  if (strlen(text) >= sizeof(request_text))
    return false;
  strcpy(request_text, text);
  xSemaphoreGive(request_ready);
  return xSemaphoreTake(response_ready, pdMS_TO_TICKS(12000)) == pdTRUE;
}
static esp_err_t event(void *, system_event_t *event) {
  if (event->event_id == SYSTEM_EVENT_STA_GOT_IP) {
    connected = true;
    snprintf(ip, sizeof(ip), IPSTR,
             IP2STR(&event->event_info.got_ip.ip_info.ip));
  }
  if (event->event_id == SYSTEM_EVENT_STA_DISCONNECTED) {
    last_disconnect_reason = event->event_info.disconnected.reason;
    if (connected)
      ++disconnects;
    connected = false;
  }
  return ESP_OK;
}
static esp_http_client_handle_t open(const Settings &current, const char *path,
                                     int bytes, const char *boot, bool result,
                                     bool get = false,
                                     const char *range = NULL) {
  char url[256];
  snprintf(url, sizeof(url), "https://%s:%u%s", current.host,
           (unsigned)current.port, path);
  esp_http_client_config_t cfg = {};
  cfg.url = url;
  cfg.cert_pem = ca_start;
  cfg.method = get ? HTTP_METHOD_GET : HTTP_METHOD_POST;
  cfg.timeout_ms = 30000;
  cfg.buffer_size = 1024;
  if (!connection)
    connection = esp_http_client_init(&cfg);
  esp_http_client_handle_t client = connection;
  if (!client)
    return NULL;
  esp_http_client_set_url(client, url);
  esp_http_client_set_method(client, cfg.method);
  esp_http_client_set_header(client, "Range", range ? range : "");
  char auth[72];
  snprintf(auth, sizeof(auth), "Bearer %s", current.token);
  esp_http_client_set_header(client, "Authorization", auth);
  esp_http_client_set_header(client, "Accept-Encoding", "identity");
  esp_http_client_set_header(client, "Content-Type",
                             "application/octet-stream");
  esp_http_client_set_header(client, "X-Micros-Boot", boot ? boot : "");
  if (result)
    esp_http_client_set_header(client, "X-Micros-Result", "200");
  stage = "tls_connect";
  if (esp_http_client_open(client, bytes) != ESP_OK ||
      (bytes && esp_http_client_write(client, response_text, bytes) != bytes)) {
    disconnect_tls();
    return NULL;
  }
  return client;
}
static int exchange(const Settings &current, const char *path, const char *boot,
                    bool result, unsigned bytes, size_t &received) {
  received = 0;
  auto client = open(current, path, bytes, boot, result);
  if (!client)
    return -1;
  stage = "headers";
  int length = esp_http_client_fetch_headers(client),
      status = esp_http_client_get_status_code(client);
  if (length < 0 || length > (int)sizeof(wire))
    status = -1;
  else {
    while (received < (size_t)length) {
      int n = esp_http_client_read(client, (char *)wire + received,
                                   length - received);
      if (n <= 0) {
        status = -1;
        break;
      }
      received += n;
    }
  }
  if (status < 0 || !esp_http_client_is_complete_data_received(client))
    disconnect_tls();
  stage = "idle";
  return status;
}
static bool download(const Settings &current) {
  char path[112], range[64];
  snprintf(path, sizeof(path), "/agent/%s/base/%s", mac, fetch_hash);
  unsigned total = embedded_base_ota_size();
  if (total < 256 || total > 0xb0000)
    return false;
  uint64_t deadline = esp_timer_get_time() + 240000000;
  // Keep the response plus HTTP/TLS headers small enough for a fragmented heap.
  // A failed read can retry the same range: flash writes accept duplicates only
  // when their already-written bytes match. Never retry activation here.
  for (unsigned offset = 0; offset < total; offset += 1024) {
    unsigned count = total - offset;
    if (count > 1024)
      count = 1024;
    snprintf(range, sizeof(range), "bytes=%u-%u", offset, offset + count - 1);
    bool complete = false;
    for (unsigned attempt = 0; attempt < 3 && !complete; ++attempt) {
      if ((uint64_t)esp_timer_get_time() >= deadline)
        return false;
      auto client = open(current, path, 0, NULL, false, true, range);
      bool ok = client != NULL;
      if (ok) {
        int length = esp_http_client_fetch_headers(client);
        ok = esp_http_client_get_status_code(client) == 206 && length == (int)count;
      }
      stage = "base_download";
      for (unsigned cursor = 0; ok && cursor < count; cursor += 256) {
        unsigned chunk = count - cursor;
        if (chunk > 256)
          chunk = 256;
        unsigned used = 0;
        while (used < chunk && (uint64_t)esp_timer_get_time() < deadline) {
          int n = esp_http_client_read(client, (char *)wire + used, chunk - used);
          if (n <= 0)
            break;
          used += n;
        }
        if (used != chunk) {
          ok = false;
          break;
        }
        unsigned padded = (chunk + 63) & ~63u;
        memset(wire + chunk, 255, padded - chunk);
        if (!embedded_base_ota_write(offset + cursor, wire, padded)) {
          disconnect_tls();
          return false;
        }
        vTaskDelay(1);
      }
      complete = ok && esp_http_client_is_complete_data_received(client);
      if (!complete) {
        disconnect_tls();
        vTaskDelay(pdMS_TO_TICKS(200));
      }
    }
    if (!complete)
      return false;
  }
  return true;
}
static void run(void *) {
  char boot[17], path[112], cid[33] = {};
  snprintf(boot, sizeof(boot), "%08x%08x", esp_random(), esp_random());
  bool pending = false;
  for (;;) {
    Settings current;
    taskENTER_CRITICAL();
    current = settings;
    bool reset = reconnect;
    reconnect = false;
    taskEXIT_CRITICAL();
    if (reset) {
      disconnect_tls();
      esp_wifi_disconnect();
      connected = false;
      profile = 0;
    }
    if (!current.ssid[0][0]) {
      vTaskDelay(pdMS_TO_TICKS(1000));
      continue;
    }
    if (!connected) {
      disconnect_tls();
      unsigned selected = profile && current.ssid[1][0] ? 1 : 0;
      wifi_config_t cfg = {};
      strcpy((char *)cfg.sta.ssid, current.ssid[selected]);
      strcpy((char *)cfg.sta.password, current.password[selected]);
      esp_wifi_set_config(ESP_IF_WIFI_STA, &cfg);
      esp_wifi_connect();
      for (unsigned i = 0; i < 50 && !connected; ++i)
        vTaskDelay(pdMS_TO_TICKS(100));
      if (!connected) {
        esp_wifi_disconnect();
        profile ^= 1;
        continue;
      }
      active_profile = selected;
      profile = 0;
    }
    if (!sntp_enabled()) {
      sntp_setoperatingmode(SNTP_OPMODE_POLL);
      sntp_setservername(0, (char *)"pool.ntp.org");
      sntp_init();
    }
    if (!current.host[0] || time(NULL) < 1700000000) {
      stage = "time_sync";
      vTaskDelay(pdMS_TO_TICKS(1000));
      continue;
    }
    size_t received;
    if (pending) {
      snprintf(path, sizeof(path), "/agent/%s/result/%s", mac, cid);
      last_http = exchange(current, path, NULL, true, response_bytes, received);
      if (last_http != 200 && last_http != 400) {
        vTaskDelay(pdMS_TO_TICKS(2000));
        continue;
      }
      if (last_http == 200 && reboot_after_reply)
        restart();
      reboot_after_reply = false;
      pending = false;
      release_response();
    }
    if (fetch_pending) {
      bool ok = download(current);
      fetch_pending = false;
      snprintf(path, sizeof(path), "RPC %u 0 0 0 %s -", ok ? 15u : 17u, fetch_actor);
      if (!command(path)) {
        vTaskDelete(NULL);
        return;
      }
      if (reboot_after_reply)
        restart();
    }
    if (!command("RPC 0 0 0 0 - -")) {
      vTaskDelete(NULL);
      return;
    }
    snprintf(path, sizeof(path), "/agent/%s/poll", mac);
    last_http = exchange(current, path, boot, false, response_bytes, received);
    release_response();
    if (last_http == 200 && received >= 64 && !memcmp(wire, "MRL1", 4)) {
      uint32_t bytes;
      memcpy(&bytes, wire + 48, 4);
      if (bytes == received - 64 && bytes < sizeof(request_text) &&
          !memchr(wire + 64, 0, bytes)) {
        const char *hex = "0123456789abcdef";
        for (unsigned i = 0; i < 16; ++i) {
          cid[2 * i] = hex[wire[4 + i] >> 4];
          cid[2 * i + 1] = hex[wire[4 + i] & 15];
        }
        cid[32] = 0;
        if (wire[20] == 18) {
          memcpy(request_text, wire + 64, bytes);
          request_text[bytes] = 0;
        } else
          strcpy(request_text, wire[20] == 0   ? "RPC 0 0 0 0 - -"
                               : wire[20] == 1 ? "RPC 1 0 0 0 - -"
                                               : "UNSUPPORTED");
        xSemaphoreGive(request_ready);
        if (xSemaphoreTake(response_ready, pdMS_TO_TICKS(12000)) != pdTRUE) {
          vTaskDelete(NULL);
          return;
        }
        pending = true;
      }
    }
    memset(wire, 0, sizeof(wire));
    vTaskDelay(pdMS_TO_TICKS(last_http < 0 ? 2000 : 100));
  }
}
void embedded_network_start() {
  nvs_handle h;
  if (nvs_open("micros_wifi", NVS_READONLY, &h) == ESP_OK) {
    size_t n = sizeof(settings);
    if (nvs_get_blob(h, "settings", &settings, &n) != ESP_OK ||
        n != sizeof(settings))
      memset(&settings, 0, sizeof(settings));
    nvs_close(h);
  }
  // Bound all persisted strings before treating them as C strings.
  for (unsigned i = 0; i < 2; ++i) {
    settings.ssid[i][32] = 0;
    settings.password[i][64] = 0;
  }
  settings.host[127] = 0;
  settings.token[64] = 0;
  tcpip_adapter_init();
  esp_event_loop_init(event, NULL);
  wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
  esp_wifi_init(&cfg);
  esp_wifi_set_storage(WIFI_STORAGE_RAM);
  esp_wifi_set_mode(WIFI_MODE_STA);
  uint8_t address[6];
  esp_wifi_get_mac(ESP_IF_WIFI_STA, address);
  snprintf(mac, sizeof(mac), "%02x%02x%02x%02x%02x%02x", address[0], address[1],
           address[2], address[3], address[4], address[5]);
  esp_wifi_start();
  request_ready = xSemaphoreCreateBinary();
  response_ready = xSemaphoreCreateBinary();
  xTaskCreate(run, "relay", 6144, NULL, 1, &worker);
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
