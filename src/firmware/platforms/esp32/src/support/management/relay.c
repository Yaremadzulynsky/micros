#include "relay.h"
#include <micros/transport.h>
#include <micros/update.h>
#include "board_profile.h"
#include <micros/deployment.h>
#include "esp_http_client.h"
#include "esp_mac.h"
#include "esp_netif_sntp.h"
#include "esp_random.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#if CONFIG_MICROS_RELAY_ENABLED
/* Fixed 64-byte relay envelope followed by at most one 12,352-byte native image. */
#define RELAY_HEADER_BYTES 64u
#define RELAY_WIRE_BYTES (RELAY_HEADER_BYTES + MICROS_BOARD_IMAGE_BYTES)
/* HTTP/TLS is blocking on this lower-priority resident worker, never an app worker. */
#define RELAY_STACK_BYTES (8u * 1024u)
/* Retry failures every two seconds without spinning or blocking the controller. */
#define RELAY_RETRY_MS 2000u
/* Reuse the same TLS worker for bounded stream batches. Full status is sampled
 * every five seconds, not per sample. No new socket or service worker. */
#define STREAM_INTERVAL_MS 50u
#define STREAM_POLL_BYTES 8192u
static TaskHandle_t relay_task;
/* One worker owns one reusable TLS connection; avoid a handshake per heartbeat. */
static esp_http_client_handle_t relay_client;
extern const unsigned char relay_ca_start[] asm("_binary_relay_ca_pem_start");

/** Bounded HTTP receive storage; the request body remains owned by the caller. */
typedef struct {
    uint8_t *data;
    size_t bytes;
    size_t capacity;
    int overflow;
} relay_response_t;

static esp_err_t receive_event(esp_http_client_event_t *event)
{
    relay_response_t *response = event->user_data;
    if (event->event_id == HTTP_EVENT_ON_DATA) {
        if (event->data_len < 0 || (size_t)event->data_len > response->capacity - response->bytes) {
            response->overflow = 1;
            return ESP_FAIL;
        }
        memcpy(response->data + response->bytes, event->data, event->data_len);
        response->bytes += event->data_len;
    }
    return ESP_OK;
}

static int exchange(const char *path, const char *boot, int result,
                    const char *body, relay_response_t *response)
{
    char url[256];
    if (snprintf(url, sizeof(url), "%s%s", CONFIG_MICROS_RELAY_URL, path) >= sizeof(url))
        return -1;
    esp_http_client_config_t config = {
        .url = url, .cert_pem = (const char *)relay_ca_start,
        .timeout_ms = 10000, /* Longer than the server's five-second poll wait. */
        .event_handler = receive_event, .user_data = response,
        .disable_auto_redirect = true, .keep_alive_enable = true,
    };
    if (!relay_client)
        relay_client = esp_http_client_init(&config);
    esp_http_client_handle_t client = relay_client;
    if (!client)
        return -1;
    esp_http_client_set_url(client, url);
    char authorization[72]; /* "Bearer " plus the provisioned 64-hex token and NUL. */
    snprintf(authorization, sizeof(authorization), "Bearer %s", CONFIG_MICROS_RELAY_TOKEN);
    esp_http_client_set_header(client, "Authorization", authorization);
    esp_http_client_set_header(client, "Content-Type", "application/octet-stream");
    esp_http_client_delete_header(client, "X-Micros-Boot");
    esp_http_client_delete_header(client, "X-Micros-Result");
    if (boot)
        esp_http_client_set_header(client, "X-Micros-Boot", boot);
    if (result) {
        char code[4];
        snprintf(code, sizeof(code), "%d", result);
        esp_http_client_set_header(client, "X-Micros-Result", code);
    }
    esp_http_client_set_method(client, HTTP_METHOD_POST);
    esp_http_client_set_post_field(client, body, strlen(body));
    response->bytes = 0;
    response->overflow = 0;
    esp_err_t error = esp_http_client_perform(client);
    int status = error == ESP_OK && !response->overflow ? esp_http_client_get_status_code(client) : -1;
    if (error != ESP_OK || response->overflow) {
        esp_http_client_cleanup(client);
        relay_client = NULL;
    }
    return status;
}
static uint32_t read_u32(const uint8_t *data)
{
    return (uint32_t)data[0] | (uint32_t)data[1] << 8 | (uint32_t)data[2] << 16 | (uint32_t)data[3] << 24;
}
static void hex_bytes(char *output, const uint8_t *data, size_t bytes)
{
    static const char hex[] = "0123456789abcdef";
    for (size_t index = 0; index < bytes; ++index) {
        output[index * 2] = hex[data[index] >> 4];
        output[index * 2 + 1] = hex[data[index] & 15];
    }
    output[bytes * 2] = 0;
}
static int decode_command(relay_response_t *response, micros_management_request_t *request,
                          char command_id[33])
{
    const uint8_t *wire = response->data;
    if (response->bytes < RELAY_HEADER_BYTES || (memcmp(wire, "MRL1", 4) && memcmp(wire, "MRS1", 4)))
        return 0;
    uint32_t bytes = read_u32(wire + 48);
    if (bytes != response->bytes - RELAY_HEADER_BYTES || wire[20] > MICROS_MANAGEMENT_PLATFORM_COMMAND ||
        wire[21] >= 2 || wire[22] >= MICROS_BOARD_IMAGE_SLOTS || wire[23])
        return 0;
    memset(request, 0, sizeof(*request));
    request->response=(char *)(request+1);request->response_capacity=MICROS_MANAGEMENT_RESPONSE_BYTES;
    request->response[0]=0;
    request->operation = wire[20];
    request->bank = wire[21];
    request->slot = wire[22];
    request->log_cursor = read_u32(wire + 24) | (uint64_t)read_u32(wire + 28) << 32;
    request->body = wire + RELAY_HEADER_BYTES;
    request->body_bytes = bytes;
    /* Activation carries SHA-256; session acquisition adds a 32-bit generation. */
    size_t maximum = request->operation == MICROS_MANAGEMENT_BASE_BEGIN ? MICROS_BASE_HEADER_BYTES :
        request->operation == MICROS_MANAGEMENT_BASE_CHUNK ? MICROS_BASE_CHUNK_BYTES :
        request->operation == MICROS_MANAGEMENT_BASE_CONFIRM ? 32u :
        request->operation == MICROS_MANAGEMENT_IMAGE ? MICROS_BOARD_IMAGE_BYTES :
        request->operation == MICROS_MANAGEMENT_GRAPH ? sizeof(micros_device_graph_t) :
        request->operation == MICROS_MANAGEMENT_ACTIVATE ? 32u :
        request->operation == MICROS_MANAGEMENT_SESSION_BEGIN ? 36u :
        request->operation == MICROS_MANAGEMENT_WIFI_SET ? 404u :
        request->operation == MICROS_MANAGEMENT_PLATFORM_COMMAND ? 255u : 0u;
    if (bytes > maximum)
        return 0;
    hex_bytes(command_id, wire + 4, 16);
    hex_bytes(request->session, wire + 32, 16);
    if (strspn(request->session, "0") == 32)
        request->session[0] = 0;
    if (!memcmp(wire,"MRS1",4)) {
        if (request->operation != MICROS_MANAGEMENT_PLATFORM_COMMAND || bytes < 10 ||
            memcmp(request->body,"IPC DRAIN ",10) || request->session[0] ||
            request->log_cursor < STREAM_INTERVAL_MS || request->log_cursor > 500) return 0;
        return 2;
    }
    return 1;
}

static void relay_worker(void *unused)
{
    (void)unused;
    uint8_t mac[6], boot_bytes[8];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    esp_fill_random(boot_bytes, sizeof(boot_bytes));
    char device[13], boot[17], command_id[33] = {0}, path[112];
    hex_bytes(device, mac, sizeof(mac));
    hex_bytes(boot, boot_bytes, sizeof(boot_bytes));
    relay_response_t response = {.capacity = RELAY_WIRE_BYTES};
    response.data = malloc(response.capacity);
    micros_management_request_t *request = calloc(1, sizeof(*request) + MICROS_MANAGEMENT_RESPONSE_BYTES);
    if (request) { request->response=(char *)(request+1); request->response_capacity=MICROS_MANAGEMENT_RESPONSE_BYTES; }
    char *stream_body = NULL; /* Allocate only while viewers request streaming. */
    if (!response.data || !request) {
        free(response.data);
        free(request);
        free(stream_body);
        printf("RELAY allocation failed\n");
        relay_task = NULL;
        vTaskDelete(NULL);
        return;
    }
    int pending_result = 0, pending_stream = 0, need_status = 1;
    size_t stream_bytes = 0;
    TickType_t last_status = xTaskGetTickCount();
    for (;;) {
        if (time(NULL) < 1704067200) {
            vTaskDelay(pdMS_TO_TICKS(RELAY_RETRY_MS));
            continue;
        }
        if (pending_result) {
            snprintf(path, sizeof(path), "/agent/%s/result/%s", device, command_id);
            int result_status = exchange(path, NULL, pending_result, request->response, &response);
            if (result_status != 200 && result_status != 400) {
                vTaskDelay(pdMS_TO_TICKS(RELAY_RETRY_MS));
                continue; /* Retry result delivery, never the operation itself. */
            }
            if (result_status == 400)
                printf("RELAY server no longer accepts the saved result; operation will not be replayed\n");
            pending_result = 0;
        }
        TickType_t now = xTaskGetTickCount();
        int heartbeat = need_status || !pending_stream || (TickType_t)(now-last_status) >= pdMS_TO_TICKS(5000);
        if (heartbeat) {
            memset(request, 0, sizeof(*request));
            request->response=(char *)(request+1);request->response_capacity=MICROS_MANAGEMENT_RESPONSE_BYTES;
            request->response[0]=0;
            request->operation = MICROS_MANAGEMENT_STATUS;
            if (micros_management_execute(request) != 200) {
                vTaskDelay(pdMS_TO_TICKS(RELAY_RETRY_MS));
                continue;
            }
        }
        const char *body = request->response;
        if (pending_stream) {
            /* stream_bytes excludes the outer closing brace, allowing a status
             * heartbeat to share a batch. Retries preserve identical batch IDs. */
            int appended=snprintf(stream_body+stream_bytes,STREAM_POLL_BYTES-stream_bytes,
                heartbeat ? ",\"status\":%s}" : "%s}", heartbeat ? request->response : "");
            if (appended < 0 || (size_t)appended >= STREAM_POLL_BYTES-stream_bytes) {
                pending_stream=0; need_status=1; continue;
            }
            body=stream_body;
        }
        snprintf(path, sizeof(path), "/agent/%s/poll", device);
        int status = exchange(path, boot, 0, body, &response);
        if (status != 200 && status != 204) {
            /* Retry the saved batch, not another read. After a server restart a
             * fresh status reestablishes presence; unknown old frames are dropped. */
            need_status=1;
            vTaskDelay(pdMS_TO_TICKS(RELAY_RETRY_MS));
            continue;
        }
        if (heartbeat) { last_status=now; need_status=0; }
        pending_stream=0;
        int kind = status == 200 ? decode_command(&response,request,command_id) : 0;
        if (kind != 2) { free(stream_body); stream_body=NULL; }
        if (kind) {
            if (kind==2) {
                if (!stream_body) stream_body=malloc(STREAM_POLL_BYTES);
                if (!stream_body) { need_status=1; vTaskDelay(pdMS_TO_TICKS(RELAY_RETRY_MS)); continue; }
                vTaskDelay(pdMS_TO_TICKS((uint32_t)request->log_cursor));
            }
            int result=micros_management_execute(request);
            if (kind==2) {
                if(result!=200) snprintf(request->response,request->response_capacity,"{\"events\":[],\"error\":-3}");
                int written=snprintf(stream_body,STREAM_POLL_BYTES,
                    "{\"stream\":{\"id\":\"%s\",\"batch\":%s}",command_id,request->response);
                if(written>0 && (size_t)written<STREAM_POLL_BYTES-1) {
                    stream_bytes=(size_t)written; pending_stream=1;
                } else need_status=1;
            } else {
                pending_result=result;
                if(result==503) snprintf(request->response,request->response_capacity,"{\"error\":\"controller busy\"}");
            }
            for (volatile uint8_t *p=response.data; p<response.data+response.bytes; ++p) *p=0;
        } else if (status==200) {
            need_status=1;
            vTaskDelay(pdMS_TO_TICKS(RELAY_RETRY_MS));
        }
    }
}
void micros_relay_start(void)
{
    if (relay_task)
        return;
    esp_sntp_config_t time_config = ESP_NETIF_SNTP_DEFAULT_CONFIG("pool.ntp.org");
    /* The resident relay owns time synchronization; reconnects do not restart it. */
    static int time_started;
    if (!time_started) {
        if (esp_netif_sntp_init(&time_config) == ESP_OK)
            time_started = 1;
    }
    if (xTaskCreate(relay_worker, "micros-relay", RELAY_STACK_BYTES, NULL, 3, &relay_task) != pdPASS)
        printf("RELAY task creation failed\n");
}
#else
void micros_relay_start(void) {}
#endif
