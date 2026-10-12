/* Real controller/parser/status, with inert storage/hardware. No native execution. */
#include "../../src/firmware/controller/controller.c"
#include <assert.h>
#undef puts
#undef printf
#undef fflush
#define micros_wifi_insights unused_wifi_insights
#include "fake/src/network.c"
#undef micros_wifi_insights
#define micros_base_status unused_base_status
#include "fake/src/update.c"
#undef micros_base_status
size_t micros_wifi_insights(char *out, size_t capacity) { return (size_t)snprintf(out, capacity, "{}"); }
size_t micros_base_status(char *out, size_t capacity) { return (size_t)snprintf(out, capacity, "{\"version\":0}"); }
void micros_platform_telemetry(micros_hardware_snapshot_t *out) { memset(out, 0, sizeof(*out)); out->profile="fixture"; }

static char *reply(const char *text)
{
    char line[600]; assert(strlen(text)<sizeof(line)); strcpy(line,text);
    char *result=micros_controller_rpc_reply(line,1); assert(result); return result;
}
int main(void)
{
    service_boot=UINT64_MAX;
    const char *valid[]={"RPC 0 0 0 0 - -", "RPC 0 0 0 4294967296 - -",
        "RPC 0 1 3 18446744073709551615 0123456789abcdef0123456789abcdef -"};
    for(unsigned i=0;i<sizeof(valid)/sizeof(valid[0]);++i) {
        char *result=reply(valid[i]);
        assert(strstr(result,"\"result\":0,"));
        assert(strstr(result,"\"service_boot\":\"18446744073709551615\""));
        assert(strstr(result,"\"base_ota\":{\"version\":0}"));
        free(result);
    }
    const char *invalid[]={"", "R", "RPC", "RPC 0 0 0 0 -", "RPC 0 0 0 0 - ",
        "RPC 0 0 0 18446744073709551616 - -", "RPC 0 0 0 -1 - -", "RPC 0 0 0 +1 - -",
        "RPC 0 0 0 0junk - -", "RPC 4294967296 0 0 0 - -", "RPC 30 0 0 0 - -",
        "RPC 0 2 0 0 - -", "RPC 0 0 4 0 - -", "RPC 0 0 0 0 badsession -",
        "RPC 0 0 0 0 0123456789abcdef0123456789abcdef0 -", "RPC 0 0 0 0 - 0",
        "RPC 0 0 0 0 - gg", "RPC 0 0 0 0 - - junk"};
    for(unsigned i=0;i<sizeof(invalid)/sizeof(invalid[0]);++i) {
        char *result=reply(invalid[i]); assert(strstr(result,"\"result\":-1")); free(result);
    }
    puts("portable RPC and status passed"); return 0;
}
