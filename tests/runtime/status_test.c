#include <micros/status.h>
#include <micros/network_status.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
static size_t network(char *out, size_t size)
{ int n = snprintf(out, size, "{\"enabled\":false}"); return n < 0 || (size_t)n >= size ? 0 : (size_t)n; }
int main(void)
{
    micros_runtime_config_t config = micros_runtime_default_config();
    micros_runtime_t *runtime = micros_runtime_create(&config);
    assert(runtime);
    assert(!micros_runtime_channel_create(runtime, 1, 1, 2, 32));
    micros_gpio_snapshot_t pin = {.name="led", .pin=13, .line=0, .output=1, .level=1};
    micros_hardware_snapshot_t hardware = {.profile="test", .flash_mb=8, .recovery_pin=-1,
        .gpio=&pin, .gpio_count=1, .internal_total=1024, .runtime_allocations_internal=1};
    char output[2048] = "{\"result\":0";
    size_t used = micros_status_append(output, sizeof(output), strlen(output), runtime, &hardware, network);
    assert(used < sizeof(output));
    assert(strstr(output, "\"profile\":\"test\"") && strstr(output, "\"heap_accounting\""));
    assert(strstr(output, "\"key\":1") && strstr(output, "\"payload_bytes\":32"));
    /* An overflowing reporter must saturate without writing beyond the bound. */
    memset(output, 0x7f, sizeof(output));
    assert(micros_status_append(output, 16, 0, runtime, &hardware, network) == 16);
    assert((unsigned char)output[16] == 0x7f);
    assert(!micros_runtime_channel_destroy(runtime, 1));
    assert(!micros_runtime_destroy(runtime));
    micros_network_snapshot_t net = {.stage="idle", .mac="001122334455", .ip="0.0.0.0",
                                      .profile_index=-1};
    assert(micros_network_status_json(output, sizeof(output), &net));
    assert(strstr(output, "\"rssi_dbm\":null") && strstr(output, "\"last_disconnect_reason\":null"));
    net.connected=1; net.rssi_known=1; net.rssi_dbm=-42; net.firmware="1.0";
    assert(micros_network_status_json(output, sizeof(output), &net));
    assert(strstr(output, "\"rssi_dbm\":-42") && strstr(output, "\"firmware\":\"1.0\""));
    assert(!micros_network_status_json(output, 8, &net));
    puts("shared status reporting passed");
}
