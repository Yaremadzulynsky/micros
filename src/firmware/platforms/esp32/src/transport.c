#include "../../../kernel/support/integer.h"
#include <micros/transport.h>
#include <micros/update.h>
#include "support/management/relay.h"
#include "activation.h"
#include "support/board_profile.h"
#include <micros/deployment.h>
#include "driver/gpio.h"
#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_https_server.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "esp_random.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "management_auth.h"
#include "nvs_flash.h"
#include "sdkconfig.h"
#include <micros/network.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>

#if CONFIG_MICROS_REMOTE_ENABLED
/* One TLS server worker and one queued controller operation bound concurrency.
 * Ten seconds bounds complete upload reception, beyond per-socket receive timeout. */
#define RECEIVE_DEADLINE_US INT64_C(10000000)
#define HTTPS_STACK_BYTES (12u * 1024u)
#define MAX_HTTP_CLIENTS 2u
static QueueHandle_t requests;
static SemaphoreHandle_t completed;
static SemaphoreHandle_t dispatch_lock;
static SemaphoreHandle_t log_lock;
static micros_management_handler_t controller;
static httpd_handle_t https_server;
static uint8_t log_ring[MICROS_MANAGEMENT_LOG_BYTES];
static size_t log_position, log_count;
static uint64_t log_total;
static uint32_t log_boot_id[2]; /* Random 64-bit boot identity separates cursor epochs. */

void micros_management_log(const uint8_t *message, size_t bytes)
{
    if (!log_lock)
        return;
    xSemaphoreTake(log_lock, portMAX_DELAY);
    for (size_t index = 0; index < bytes; ++index) {
        log_ring[log_position] = message[index];
        log_position = (log_position + 1) % sizeof(log_ring);
        if (log_count < sizeof(log_ring))
            ++log_count;
        ++log_total;
    }
    xSemaphoreGive(log_lock);
}
size_t micros_transport_read_log(uint8_t *out,size_t capacity)
{
    if (!log_lock) return 0;
    xSemaphoreTake(log_lock, portMAX_DELAY);
    size_t count=log_count<capacity?log_count:capacity;
    for (size_t i=0;i<count;++i)
        out[i]=log_ring[(log_position+sizeof(log_ring)-count+i)%sizeof(log_ring)];
    xSemaphoreGive(log_lock);
    return count;
}
static int parse_log_cursor(const char *query, uint64_t *cursor)
{
    if (strncmp(query, "cursor=", 7)) return 0;
    const char *field = query + 7;
    return micros_parse_u64(&field, 10, cursor) && !*field;
}
static esp_err_t unavailable_response(httpd_req_t *request, const char *message)
{
    httpd_resp_set_status(request, "503 Service Unavailable");
    return httpd_resp_sendstr(request, message);
}
int micros_management_execute(micros_management_request_t *message)
{
    if (!requests || !dispatch_lock)
        return 503;
    micros_management_operation_t operation = message->operation;
    if (operation == MICROS_MANAGEMENT_LOG_STREAM) {
        /* Hex preserves arbitrary diagnostic bytes without JSON/UTF-8 escaping.
         * 1536 bytes leave room for metadata in the 4096-byte response. */
        const size_t chunk_bytes = 1536;
        xSemaphoreTake(log_lock, portMAX_DELAY);
        uint64_t oldest = log_total - log_count;
        uint64_t requested = message->log_cursor <= log_total ? message->log_cursor : 0;
        uint64_t start = requested < oldest ? oldest : requested;
        size_t count = log_total - start;
        if (count > chunk_bytes)
            count = chunk_bytes;
        size_t used = (size_t)snprintf(message->response, message->response_capacity,
            "{\"boot_id\":\"%08" PRIx32 "%08" PRIx32 "\",\"start\":%s"
            ",\"next\":%s,\"lost\":%s,\"end\":%s,\"data_hex\":\"",
            log_boot_id[0], log_boot_id[1], micros_decimal(start).text, micros_decimal(start + count).text, micros_decimal(start - requested).text, micros_decimal(log_total).text);
        static const char hex[] = "0123456789abcdef";
        for (size_t index = 0; index < count; ++index) {
            uint8_t value = log_ring[(log_position + sizeof(log_ring) - (log_total - start) + index) % sizeof(log_ring)];
            message->response[used++] = hex[value >> 4];
            message->response[used++] = hex[value & 15];
        }
        memcpy(message->response + used, "\"}", 3);
        xSemaphoreGive(log_lock);
    } else if (operation == MICROS_MANAGEMENT_LOGS) {
        /* HTTP response capacity bounds the most recent part of the larger log ring. */
        xSemaphoreTake(log_lock, portMAX_DELAY);
        size_t count =
            log_count < message->response_capacity ? log_count : message->response_capacity - 1;
        for (size_t index = 0; index < count; ++index)
            message->response[index] = (char)
                log_ring[(log_position + sizeof(log_ring) - count + index) % sizeof(log_ring)];
        xSemaphoreGive(log_lock);
    } else {
        if (xSemaphoreTake(dispatch_lock, 0) != pdTRUE)
            return 503;
        if (xQueueSend(requests, &message, 0) != pdTRUE) {
            xSemaphoreGive(dispatch_lock);
            return 503;
        }
        /* The pointer remains owned here until the controller completes. Never
         * free an in-flight request on a client timeout; reset is whole-device recovery. */
        xSemaphoreTake(completed, portMAX_DELAY);
        xSemaphoreGive(dispatch_lock);
    }
    return message->result ? 409 : 200;
}
static esp_err_t handle_request(httpd_req_t *request)
{
    char authorization[MICROS_MANAGEMENT_BEARER_BYTES + MICROS_MANAGEMENT_TOKEN_BYTES + 1];
    size_t authorization_bytes = httpd_req_get_hdr_value_len(request, "Authorization");
    if (authorization_bytes >= sizeof(authorization) ||
        httpd_req_get_hdr_value_str(request, "Authorization", authorization,
                                    sizeof(authorization)) != ESP_OK ||
        !micros_management_authorized(authorization, authorization_bytes,
                                      CONFIG_MICROS_MANAGEMENT_TOKEN)) {
        httpd_resp_set_status(request, "401 Unauthorized");
        return httpd_resp_sendstr(request, "authentication required");
    }
    micros_management_operation_t operation =
        (micros_management_operation_t)(uintptr_t)request->user_ctx;
    size_t maximum = operation == MICROS_MANAGEMENT_BASE_BEGIN ? MICROS_BASE_HEADER_BYTES
                     : operation == MICROS_MANAGEMENT_BASE_CHUNK ? MICROS_BASE_CHUNK_BYTES
                     : operation == MICROS_MANAGEMENT_BASE_CONFIRM ? 32u
                     : operation == MICROS_MANAGEMENT_IMAGE      ? MICROS_BOARD_IMAGE_BYTES
                     : operation == MICROS_MANAGEMENT_GRAPH    ? sizeof(micros_device_graph_t)
                     : operation == MICROS_MANAGEMENT_ACTIVATE ? MICROS_ACTIVATION_HASH_BYTES
                     : operation == MICROS_MANAGEMENT_SESSION_BEGIN ? MICROS_ACTIVATION_HASH_BYTES + 4u
                     : operation == MICROS_MANAGEMENT_PLATFORM_COMMAND ? 255u
                     : operation == MICROS_MANAGEMENT_WIFI_SET ? 404u
                                                               : 0u;
    if (request->content_len > maximum) {
        httpd_resp_set_status(request, "413 Payload Too Large");
        return httpd_resp_sendstr(request, "request exceeds service-store bound");
    }
    micros_management_request_t *message = calloc(1, sizeof(*message) + MICROS_MANAGEMENT_RESPONSE_BYTES);
    if (message) { message->response=(char *)(message+1); message->response_capacity=MICROS_MANAGEMENT_RESPONSE_BYTES; }
    uint8_t *body = request->content_len ? malloc(request->content_len) : NULL;
    if (!message || (request->content_len && !body)) {
        free(message);
        free(body);
        return unavailable_response(request, "management capacity");
    }
    message->operation = operation;
    size_t session_bytes = httpd_req_get_hdr_value_len(request, "X-Micros-Session");
    if (session_bytes) {
        if (session_bytes != sizeof(message->session) - 1 ||
            httpd_req_get_hdr_value_str(request, "X-Micros-Session", message->session,
                                       sizeof(message->session)) != ESP_OK ||
            strspn(message->session, "0123456789abcdef") != session_bytes)
            goto invalid;
    }
    char query[64] = {0}; /* Only two bounded integer identifiers, never a filename or offset. */
    if (httpd_req_get_url_query_len(request) >= sizeof(query))
        goto invalid;
    if (httpd_req_get_url_query_len(request)) {
        if (httpd_req_get_url_query_str(request, query, sizeof(query)) != ESP_OK)
            goto invalid;
        char extra;
        int fields =
            (operation == MICROS_MANAGEMENT_LOG_STREAM || operation == MICROS_MANAGEMENT_BASE_CHUNK)
                ? parse_log_cursor(query, &message->log_cursor) :
            operation == MICROS_MANAGEMENT_IMAGE
                ? sscanf(query, "bank=%u&slot=%u%c", &message->bank, &message->slot, &extra)
                : sscanf(query, "bank=%u%c", &message->bank, &extra);
        if (fields != (operation == MICROS_MANAGEMENT_IMAGE ? 2 : 1))
            goto invalid;
    } else if (operation == MICROS_MANAGEMENT_IMAGE || operation == MICROS_MANAGEMENT_GRAPH ||
               operation == MICROS_MANAGEMENT_ACTIVATE || operation == MICROS_MANAGEMENT_BASE_CHUNK)
        goto invalid;
    if (message->bank >= 2 || message->slot >= MICROS_BOARD_IMAGE_SLOTS)
        goto invalid;
    size_t received = 0;
    int64_t deadline = esp_timer_get_time() + RECEIVE_DEADLINE_US;
    while (received < request->content_len && esp_timer_get_time() < deadline) {
        int bytes =
            httpd_req_recv(request, (char *)body + received, request->content_len - received);
        if (bytes <= 0)
            goto invalid;
        received += (size_t)bytes;
    }
    if (received != request->content_len)
        goto invalid;
    message->body = body;
    message->body_bytes = received;
    int status = micros_management_execute(message);
    httpd_resp_set_type(request,
                        operation == MICROS_MANAGEMENT_LOGS ? "text/plain" : "application/json");
    if (status != 200)
        httpd_resp_set_status(request, status == 503 ? "503 Service Unavailable" : "409 Conflict");
    esp_err_t result = httpd_resp_sendstr(request, message->response);
    if (body) for (volatile uint8_t *p = body; p < body + request->content_len; ++p) *p = 0;
    free(body);
    free(message);
    return result;
invalid:
    if (body) for (volatile uint8_t *p = body; p < body + request->content_len; ++p) *p = 0;
    free(body);
    free(message);
    return httpd_resp_send_err(request, HTTPD_400_BAD_REQUEST,
                               "invalid or incomplete service request");
}
static void start_https(void)
{
    micros_relay_start();
    if (https_server)
        return;
    httpd_ssl_config_t config = HTTPD_SSL_CONFIG_DEFAULT();
    config.httpd.stack_size = HTTPS_STACK_BYTES;
    config.httpd.task_priority = 4; /* Below base controller and runtime deadline supervisor. */
    config.httpd.max_open_sockets = MAX_HTTP_CLIENTS;
    config.httpd.max_uri_handlers = 19; /* Original routes, cursor logs, session pair and intentional pause. */
    config.httpd.recv_wait_timeout =
        3; /* Individual socket reads, under absolute upload deadline. */
    config.httpd.send_wait_timeout = 3;
    config.httpd.lru_purge_enable = true;
    extern const unsigned char certificate_start[] asm("_binary_servercert_pem_start");
    extern const unsigned char certificate_end[] asm("_binary_servercert_pem_end");
    extern const unsigned char key_start[] asm("_binary_prvtkey_pem_start");
    extern const unsigned char key_end[] asm("_binary_prvtkey_pem_end");
    config.servercert = certificate_start;
    config.servercert_len = certificate_end - certificate_start;
    config.prvtkey_pem = key_start;
    config.prvtkey_len = key_end - key_start;
    if (httpd_ssl_start(&https_server, &config) != ESP_OK) {
        printf("MANAGEMENT TLS startup failed\n");
        return;
    }
    const httpd_uri_t endpoints[] = {
        {.uri="/v1/platform-command", .method=HTTP_POST, .handler=handle_request,
         .user_ctx=(void *)MICROS_MANAGEMENT_PLATFORM_COMMAND},
        {.uri = "/v1/base-begin", .method = HTTP_POST, .handler = handle_request,
         .user_ctx = (void *)MICROS_MANAGEMENT_BASE_BEGIN},
        {.uri = "/v1/base-chunk", .method = HTTP_PUT, .handler = handle_request,
         .user_ctx = (void *)MICROS_MANAGEMENT_BASE_CHUNK},
        {.uri = "/v1/base-finish", .method = HTTP_POST, .handler = handle_request,
         .user_ctx = (void *)MICROS_MANAGEMENT_BASE_FINISH},
        {.uri = "/v1/base-confirm", .method = HTTP_POST, .handler = handle_request,
         .user_ctx = (void *)MICROS_MANAGEMENT_BASE_CONFIRM},
        {.uri = "/v1/base-abort", .method = HTTP_POST, .handler = handle_request,
         .user_ctx = (void *)MICROS_MANAGEMENT_BASE_ABORT},
                                     {.uri = "/v1/wifi", .method = HTTP_GET,
                                      .handler = handle_request, .user_ctx = (void *)MICROS_MANAGEMENT_WIFI_GET},
                                     {.uri = "/v1/wifi", .method = HTTP_PUT,
                                      .handler = handle_request, .user_ctx = (void *)MICROS_MANAGEMENT_WIFI_SET},{.uri = "/v1/status",
                                      .method = HTTP_GET,
                                      .handler = handle_request,
                                      .user_ctx = (void *)MICROS_MANAGEMENT_STATUS},
                                     {.uri = "/v1/log-stream", .method = HTTP_GET,
                                      .handler = handle_request, .user_ctx = (void *)MICROS_MANAGEMENT_LOG_STREAM},
                                     {.uri = "/v1/session", .method = HTTP_POST,
                                      .handler = handle_request, .user_ctx = (void *)MICROS_MANAGEMENT_SESSION_BEGIN},
                                     {.uri = "/v1/session", .method = HTTP_DELETE,
                                      .handler = handle_request, .user_ctx = (void *)MICROS_MANAGEMENT_SESSION_END},
                                     {.uri = "/v1/pause", .method = HTTP_POST,
                                      .handler = handle_request, .user_ctx = (void *)MICROS_MANAGEMENT_PAUSE},
                                     {.uri = "/v1/logs",
                                      .method = HTTP_GET,
                                      .handler = handle_request,
                                      .user_ctx = (void *)MICROS_MANAGEMENT_LOGS},
                                     {.uri = "/v1/image",
                                      .method = HTTP_PUT,
                                      .handler = handle_request,
                                      .user_ctx = (void *)MICROS_MANAGEMENT_IMAGE},
                                     {.uri = "/v1/graph",
                                      .method = HTTP_PUT,
                                      .handler = handle_request,
                                      .user_ctx = (void *)MICROS_MANAGEMENT_GRAPH},
                                     {.uri = "/v1/activate",
                                      .method = HTTP_POST,
                                      .handler = handle_request,
                                      .user_ctx = (void *)MICROS_MANAGEMENT_ACTIVATE},
                                     {.uri = "/v1/stop",
                                      .method = HTTP_POST,
                                      .handler = handle_request,
                                      .user_ctx = (void *)MICROS_MANAGEMENT_STOP},
                                     {.uri = "/v1/reboot",
                                      .method = HTTP_POST,
                                      .handler = handle_request,
                                      .user_ctx = (void *)MICROS_MANAGEMENT_REBOOT}};
    for (size_t index = 0; index < sizeof(endpoints) / sizeof(endpoints[0]); ++index)
        ESP_ERROR_CHECK(httpd_register_uri_handler(https_server, &endpoints[index]));
}
void micros_management_start(micros_management_handler_t handler)
{
    if (strlen(CONFIG_MICROS_MANAGEMENT_TOKEN) != MICROS_MANAGEMENT_TOKEN_BYTES) {
        printf("MANAGEMENT needs physical credential provisioning\n");
        return;
    }
    controller = handler;
    log_boot_id[0] = esp_random();
    log_boot_id[1] = esp_random();
    requests = xQueueCreate(1, sizeof(micros_management_request_t *));
    completed = xSemaphoreCreateBinary();
    dispatch_lock = xSemaphoreCreateMutex();
    log_lock = xSemaphoreCreateMutex();
    if (!requests || !completed || !log_lock || !dispatch_lock) {
        printf("MANAGEMENT allocation failed\n");
        return;
    }
    micros_wifi_start(start_https);
}
void micros_management_poll(void)
{
    micros_wifi_poll();
    if (!requests)
        return;
    micros_management_request_t *request;
    if (xQueueReceive(requests, &request, 0) == pdTRUE) {
        controller(request);
        xSemaphoreGive(completed);
    }
}
#else
size_t micros_transport_read_log(uint8_t *out,size_t capacity) { (void)out;(void)capacity;return 0; }
int micros_management_execute(micros_management_request_t *request)
{
    (void)request;
    return 503;
}
void micros_management_start(micros_management_handler_t handler)
{
    (void)handler;
}
void micros_management_poll(void)
{
}
void micros_management_log(const uint8_t *message, size_t bytes)
{
    (void)message;
    (void)bytes;
}
#endif

#include "driver/uart.h"
int micros_controller_read(uint8_t *output, size_t bytes, unsigned timeout_ms)
{ return uart_read_bytes(UART_NUM_0, output, bytes, pdMS_TO_TICKS(timeout_ms)); }
#include <micros/transport.h>
size_t micros_transport_write(const void *data,size_t bytes) {
 int n=uart_write_bytes(UART_NUM_0,data,bytes);return n>0?(size_t)n:0;
}
void micros_transport_flush(void) { uart_wait_tx_done(UART_NUM_0,pdMS_TO_TICKS(1000)); }
