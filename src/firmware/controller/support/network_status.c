#include <micros/network_status.h>
#include <stdio.h>
size_t micros_network_status_json(char *output, size_t capacity,
                                  const micros_network_snapshot_t *s)
{
    char rssi[16] = "null", reason[16] = "null", firmware[64] = "";
    if (s->rssi_known) snprintf(rssi, sizeof(rssi), "%d", s->rssi_dbm);
    if (s->disconnect_reason) snprintf(reason, sizeof(reason), "%u", s->disconnect_reason);
    if (s->firmware) snprintf(firmware, sizeof(firmware), ",\"firmware\":\"%s\"", s->firmware);
    int n = snprintf(output, capacity,
        "{\"result\":0,\"connected\":%s,\"configured\":%s,\"relay_configured\":%s,"
        "\"stack_free\":%u,\"stage\":\"%s\",\"relay_http\":%d,\"mac\":\"%s\",\"ip\":\"%s\"%s,"
        "\"rssi_dbm\":%s,\"profile_index\":%d,\"disconnects\":%u,\"last_disconnect_reason\":%s,"
        "\"profiles_api\":1,\"profiles_capacity\":2}",
        s->connected ? "true" : "false", s->configured ? "true" : "false",
        s->relay_configured ? "true" : "false", s->stack_free, s->stage, s->relay_http,
        s->mac, s->ip, firmware, rssi, s->profile_index, s->disconnects, reason);
    return n < 0 || (size_t)n >= capacity ? 0 : (size_t)n;
}
