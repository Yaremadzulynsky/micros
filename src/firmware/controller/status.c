#include "../kernel/support/integer.h"
#include <micros/status.h>
#include <micros/command.h>
#include "channel.h"
#include <inttypes.h>
#include <stdarg.h>
#include <stdio.h>
/** @brief Saturating JSON writer; never continues past a truncated field. */
static size_t append(char *output, size_t capacity, size_t used, const char *format, ...)
    __attribute__((format(printf,4,5)));
static size_t append(char *output, size_t capacity, size_t used, const char *format, ...)
{
    if (used >= capacity) return capacity;
    va_list arguments;
    va_start(arguments, format);
    int count=vsnprintf(output+used, capacity-used, format, arguments);
    va_end(arguments);
    return count<0 || (size_t)count>=capacity-used ? capacity : used+(size_t)count;
}
size_t micros_status_append(char *output, size_t capacity, size_t used, micros_runtime_t *runtime,
                           const micros_hardware_snapshot_t *hardware,
                           size_t (*network_json)(char *, size_t))
{
    const micros_gpio_snapshot_t *lines = hardware->gpio;
    unsigned line_count = hardware->gpio_count;
    used=append(output,capacity,used,",\"board\":{\"profile\":\"%s\",\"flash_mb\":%u,\"recovery_pin\":%d,\"gpio\":[",
                hardware->profile,hardware->flash_mb,hardware->recovery_pin);
    for (unsigned line=0;line<line_count;++line)
        used=append(output,capacity,used,"%s{\"name\":\"%s\",\"line\":%u,\"pin\":%d,\"output\":%s,\"level\":%d}",
                    line?",":"",lines[line].name,line,(int)lines[line].pin,lines[line].output?"true":"false",lines[line].level);
    used=append(output,capacity,used,
        "]},\"memory\":{\"internal_free\":%u,\"internal_total\":%u,\"internal_min\":%u,\"internal_largest\":%u,\"psram_total\":%u,\"psram_free\":%u},\"network\":",
        (unsigned)hardware->internal_free,
        (unsigned)hardware->internal_total,
        (unsigned)hardware->internal_min,
        (unsigned)hardware->internal_largest,
        (unsigned)hardware->external_total,
        (unsigned)hardware->external_free);
    if (used>=capacity) return capacity;
    size_t network_bytes=network_json(output+used,capacity-used);
    if (!network_bytes) return capacity;
    used+=network_bytes;
    if (hardware->runtime_allocations_internal) {
        micros_runtime_usage_t allocation = {0};
        if (runtime) allocation = micros_runtime_usage(runtime);
        used=append(output,capacity,used,
            ",\"heap_accounting\":{\"ipc_storage\":%u,\"ipc_payload_capacity\":%u,\"ipc_assigned\":%u,\"runtime_metadata\":%u,\"supervisor_stack\":%u,\"controller_stack_free\":%u,\"management_reply_reserved\":%u}",
            (unsigned)allocation.channel_storage_bytes,
            (unsigned)allocation.channel_payload_capacity,
            (unsigned)allocation.channel_bytes,
            (unsigned)(allocation.kernel_metadata_bytes-allocation.channel_storage_bytes),
            (unsigned)allocation.supervisor_stack_bytes,(unsigned)hardware->controller_stack_free,
            (unsigned)(MICROS_MANAGEMENT_RESPONSE_BYTES+32));
    }
    used=append(output,capacity,used,",\"channels\":[");
    unsigned count=0;
    for (unsigned slot=0;slot<MICROS_CHANNEL_CAPACITY;++slot) {
        micros_channel_status_t channel;
        if (micros_runtime_channel_status(runtime,slot,&channel)) continue;
        used=append(output,capacity,used,
            "%s{\"key\":%u,\"policy\":%u,\"depth\":%u,\"backlog\":%u,\"published\":%s,\"missed\":%s,\"age_us\":%s,\"payload_bytes\":%u,\"retained_bytes\":%u}",
            count++?",":"",(unsigned)channel.key,(unsigned)channel.policy,(unsigned)channel.depth,(unsigned)channel.backlog,micros_decimal(channel.published).text,micros_decimal(channel.missed).text,micros_decimal(channel.age_us).text,
            (unsigned)channel.payload_bytes,(unsigned)channel.retained_bytes);
    }
    return append(output,capacity,used,"]");
}
