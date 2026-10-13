/* Exercise the production bridge with actual runtime channels and transport. */
#include "runtime.c"
#include "../../services/network-bridge/src/service.c"
#include <assert.h>
#include <stdio.h>

static micros_runtime_t *runtime;
static micros_instance_t instances[4];
static unsigned instance_count;
#include <micros/ipc_console.h>

int main(int argc, char **argv)
{
    assert(argc == 2);
    micros_runtime_config_t config = micros_runtime_default_config();
    runtime = micros_runtime_create(&config);
    micros_instance_t bridge, peer;
    assert(runtime);
    assert(!micros_runtime_load(runtime, argv[1], 8, &bridge));
    assert(!micros_runtime_load(runtime, argv[1], 8, &peer));
    assert(!micros_runtime_channel_create(runtime, 1, MICROS_CHANNEL_STREAM, 2, 64));
    state_t state = {0};
    micros_service_args_t args = find_service(runtime, bridge)->args;
    args.arena = &state;
    /* Outbound exists first in the generated declarations: no channels opened. */
    assert(initialize(&args) != MICROS_OK);
    assert(!stop(&args));
    assert(!micros_runtime_channel_create(runtime, 2, MICROS_CHANNEL_STREAM, 2, 64));
    assert(!initialize(&args));
    find_service(runtime, bridge)->state = MICROS_STATE_RUNNING;
    micros_service_args_t peer_args = find_service(runtime, peer)->args;
    micros_handle_t publisher, subscriber;
    assert(!micros_runtime_ipc_api.ipc_open(peer_args.context, 1, MICROS_IPC_SUBSCRIBE, &subscriber));
    assert(!micros_runtime_ipc_api.ipc_open(peer_args.context, 2, MICROS_IPC_PUBLISH, &publisher));
    const uint8_t payload[] = {0x08, 0x2a, 0x18, 0x01};
    uint8_t received[64]; uint32_t bytes = 0; micros_message_info_t info;
    assert(!micros_runtime_console_write(runtime, bridge, 1, payload, sizeof(payload)));
    assert(!micros_runtime_ipc_api.ipc_read(peer_args.context, subscriber, received, sizeof(received), &bytes, &info));
    assert(bytes == sizeof(payload) && !memcmp(payload, received, bytes));
    assert(micros_runtime_console_write(runtime, bridge, 2, payload, sizeof(payload)) == MICROS_ERROR_UNSUPPORTED);
    assert(micros_runtime_console_read(runtime, bridge, 1, received, sizeof(received), &bytes, &info) == MICROS_ERROR_UNSUPPORTED);
    assert(!micros_runtime_ipc_api.ipc_publish(peer_args.context, publisher, payload, sizeof(payload)));
    assert(!idle(&args)); /* A service step must not steal the transport's cursor. */
    assert(!micros_runtime_console_read(runtime, bridge, 2, received, sizeof(received), &bytes, &info));
    assert(bytes == sizeof(payload) && !memcmp(payload, received, bytes));
    assert(micros_runtime_console_read(runtime, bridge, 2, received, sizeof(received), &bytes, &info) == MICROS_ERROR_EMPTY);
    for (unsigned i = 0; i < 3; ++i)
        assert(!micros_runtime_ipc_api.ipc_publish(peer_args.context, publisher, payload, sizeof(payload)));
    assert(micros_runtime_console_read(runtime, bridge, 2, received, sizeof(received), &bytes, &info) == MICROS_ERROR_MESSAGES_MISSED);
    assert(info.messages_missed == 1);
    assert(!micros_runtime_console_read(runtime, bridge, 2, received, sizeof(received), &bytes, &info));
    char batch[4096];
    instances[0]=bridge;instance_count=1;
    micros_ipc_command(runtime, instances, instance_count, "IPC INFO",batch,sizeof(batch));
    assert(strstr(batch,"stream=1"));
    /* Loss must precede retained data, and a batch drains both remaining samples. */
    for (unsigned i=0;i<3;i++)
        assert(!micros_runtime_ipc_api.ipc_publish(peer_args.context,publisher,payload,sizeof(payload)));
    micros_ipc_batch(runtime,bridge,2,batch,sizeof(batch));
    assert(strstr(batch,"{\"missed\":2},{\"data\":\"082a1801\"},{\"data\":\"082a1801\"}"));
    assert(strstr(batch,"\"error\":0}"));
    micros_ipc_batch(runtime,bridge,2,batch,sizeof(batch));
    assert(!strcmp(batch,"{\"events\":[],\"error\":0}"));
    /* Insufficient output space must not consume a message. */
    assert(!micros_runtime_ipc_api.ipc_publish(peer_args.context,publisher,payload,sizeof(payload)));
    micros_ipc_batch(runtime,bridge,2,batch,64);
    assert(!strcmp(batch,"{\"events\":[],\"error\":0}"));
    assert(!micros_runtime_console_read(runtime,bridge,2,received,sizeof(received),&bytes,&info));
    micros_ipc_batch(runtime,bridge,1,batch,sizeof(batch));
    assert(strstr(batch,"\"error\":-"));
    assert(!stop(&args));
    assert(!stop(&args));
    assert(find_service(runtime, bridge)->owned_handles == 0);
    assert(micros_runtime_console_write(runtime, bridge, 1, payload, sizeof(payload)) == MICROS_ERROR_UNSUPPORTED);
    /* Maximum-size records: fill a deeper channel and prove an output-bound
     * batch leaves every remaining record available to the next batch. */
    assert(!micros_runtime_ipc_api.ipc_close(peer_args.context,publisher));
    assert(!micros_runtime_channel_destroy(runtime,2));
    assert(!micros_runtime_channel_create(runtime,2,MICROS_CHANNEL_STREAM,8,256));
    assert(!initialize(&args));
    assert(!micros_runtime_ipc_api.ipc_open(peer_args.context,2,MICROS_IPC_PUBLISH,&publisher));
    uint8_t maximum[256]; memset(maximum,0xab,sizeof(maximum));
    for(unsigned i=0;i<8;i++)
        assert(!micros_runtime_ipc_api.ipc_publish(peer_args.context,publisher,maximum,sizeof(maximum)));
    unsigned delivered=0;
    for(unsigned turn=0;turn<2;turn++) {
        memset(batch,0x7f,sizeof(batch));
        micros_ipc_batch(runtime,bridge,2,batch,sizeof(batch));
        assert(strlen(batch)<MICROS_IPC_BATCH_BYTES);
        assert((unsigned char)batch[MICROS_IPC_BATCH_BYTES]==0x7f);
        const char *cursor=batch;unsigned count=0;
        while((cursor=strstr(cursor,"{\"data\":\""))) { count++; cursor+=9; }
        assert(count>0 && count<8);delivered+=count;
    }
    assert(delivered==8);
    for(unsigned i=0;i<8;i++)
        assert(!micros_runtime_ipc_api.ipc_publish(peer_args.context,publisher,payload,sizeof(payload)));
    micros_ipc_batch(runtime,bridge,2,batch,sizeof(batch));
    unsigned small=0;const char *cursor=batch;
    while((cursor=strstr(cursor,"{\"data\":\""))) { small++; cursor+=9; }
    assert(small==8);
    assert(!stop(&args));
    /* Partial init: first port opens, second fails, stop releases the first. */
    assert(!micros_runtime_channel_destroy(runtime, 1));
    assert(initialize(&args) != MICROS_OK);
    assert(find_service(runtime, bridge)->owned_handles == 1);
    assert(!stop(&args));
    assert(find_service(runtime, bridge)->owned_handles == 0);
    find_service(runtime, bridge)->state = MICROS_STATE_LOADED;
    assert(!micros_runtime_unload(runtime, bridge));
    assert(!micros_runtime_ipc_api.ipc_close(peer_args.context, subscriber));
    assert(!micros_runtime_ipc_api.ipc_close(peer_args.context, publisher));
    assert(!micros_runtime_unload(runtime, peer));
    assert(!micros_runtime_destroy(runtime));
    puts("PASS bridge forwarding, eight-event batches, maximum payload bounds, loss ordering and cleanup");
}
