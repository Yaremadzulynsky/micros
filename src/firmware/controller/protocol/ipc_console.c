#include <micros/ipc_console.h>
#include <stdio.h>
#include <string.h>
/* Privileged transport adapter: only existing service-owned ports are used.
 * No schema decoding, device-specific routing, or hardware access in the base. */
int micros_ipc_hex(char c)
{
    if(c>='0' && c<='9') return c-'0';
    if(c>='a' && c<='f') return c-'a'+10;
    if(c>='A' && c<='F') return c-'A'+10;
    return -1;
}
/* At most eight events / 3000 JSON bytes per transport turn. Reserve enough
 * room for a maximum-size message BEFORE advancing its cursor: never truncate
 * a consumed record. Empty channels return immediately; no controller waits. */
void micros_ipc_batch(micros_runtime_t *owner, micros_instance_t instance, unsigned key,
                      char *reply, size_t capacity)
{
    static const char hex[] = "0123456789abcdef";
    if (capacity > MICROS_IPC_BATCH_BYTES) capacity = MICROS_IPC_BATCH_BYTES;
    if (capacity < 64) { if (capacity) reply[0] = 0; return; }
    size_t used = (size_t)snprintf(reply,capacity,"{\"events\":[");
    int error = 0;
    for (unsigned count=0; count<8 && capacity-used >= 560; ++count) {
        uint8_t payload[256]; uint32_t bytes=0; micros_message_info_t info={0};
        micros_result_t result=micros_runtime_console_read(owner,instance,key,payload,sizeof(payload),&bytes,&info);
        if (result == MICROS_ERROR_EMPTY) break;
        if (result && result != MICROS_ERROR_MESSAGES_MISSED) { error=(int)result; break; }
        if (count) reply[used++]=',';
        if (result == MICROS_ERROR_MESSAGES_MISSED) {
            used+=(size_t)snprintf(reply+used,capacity-used,"{\"missed\":%llu}",(unsigned long long)info.messages_missed);
        } else {
            used+=(size_t)snprintf(reply+used,capacity-used,"{\"data\":\"");
            for(uint32_t i=0;i<bytes;i++) { reply[used++]=hex[payload[i]>>4]; reply[used++]=hex[payload[i]&15]; }
            reply[used++]='"'; reply[used++]='}';
        }
    }
    snprintf(reply+used,capacity-used,"],\"error\":%d}",error);
}

void micros_ipc_command(micros_runtime_t *runtime, const micros_instance_t *instances, size_t instance_count,
                        const char *command,char *reply,size_t capacity)
{
    if (!strcmp(command,"IPC INFO")) { snprintf(reply,capacity,"IPC READY protocol=1 stream=1"); return; }
    unsigned index,key; int n=0;
    uint8_t payload[256]; uint32_t bytes=0; micros_result_t result;
    if (sscanf(command,"IPC WRITE %u %u %n",&index,&key,&n)==2 && n) {
        size_t count=strlen(command+n);
        if (!count || count%2 || count>sizeof(payload)*2) { snprintf(reply,capacity,"IPC ERROR -1"); return; }
        for(size_t i=0;i<count;i+=2) {
            int hi=micros_ipc_hex(command[n+i]),lo=micros_ipc_hex(command[n+i+1]);
            if(hi<0 || lo<0) { snprintf(reply,capacity,"IPC ERROR -1"); return; }
            payload[bytes++]=(uint8_t)((hi<<4)|lo);
        }
        result= index<instance_count ? micros_runtime_console_write(runtime,instances[index],key,payload,bytes) : MICROS_ERROR_INVALID_ARGUMENT;
        snprintf(reply,capacity,result ? "IPC ERROR %d" : "IPC QUEUED %d",result ? (int)result : (int)key);
    } else if (sscanf(command,"IPC READ %u %u%n",&index,&key,&n)==2 && n && !command[n]) {
        micros_message_info_t info={0};
        result= index<instance_count ? micros_runtime_console_read(runtime,instances[index],key,payload,sizeof(payload),&bytes,&info) : MICROS_ERROR_INVALID_ARGUMENT;
        if(result==MICROS_ERROR_EMPTY) snprintf(reply,capacity,"IPC EMPTY %u",key);
        else if(result) snprintf(reply,capacity,"IPC ERROR %d",(int)result);
        else {
            size_t used=(size_t)snprintf(reply,capacity,"IPC DATA %u ",key);
            for(uint32_t i=0;i<bytes && used+2<capacity;i++)
                used+=(size_t)snprintf(reply+used,capacity-used,"%02x",payload[i]);
        }
    } else snprintf(reply,capacity,"IPC ERROR -1");
}
