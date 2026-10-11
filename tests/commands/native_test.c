/* Execute the generated dispatcher and example service against bounded fake IPC. */
#include <micros/service.h>
#include <micros/ipc.h>
#include "counter_commands.h"
#include "counter_rpc_request.codec.h"
#include "counter_rpc_response.codec.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>

struct micros_context { bool request, response; };
static uint8_t input[112], output[112];
static uint32_t input_bytes, output_bytes;
static unsigned writes;
static micros_result_t open_port(micros_context_t *c, uint32_t key, uint32_t access, micros_handle_t *handle)
{
    if (key == REQUEST_KEY) { assert(!c->request && access == MICROS_IPC_SUBSCRIBE); c->request=true; }
    else { assert(key == RESPONSE_KEY && !c->response && access == MICROS_IPC_PUBLISH); c->response=true; }
    *handle=key;
    return MICROS_OK;
}
static micros_result_t close_port(micros_context_t *c, micros_handle_t handle)
{
    if (handle == REQUEST_KEY) { assert(c->request); c->request=false; }
    else { assert(handle == RESPONSE_KEY && c->response); c->response=false; }
    return MICROS_OK;
}
static micros_result_t read_port(micros_context_t *c, micros_handle_t handle, uint8_t *data,
    uint32_t capacity, uint32_t *bytes, micros_message_info_t *info)
{
    (void)info;
    assert(c->request && handle == REQUEST_KEY);
    if (!input_bytes) return MICROS_ERROR_EMPTY;
    assert(capacity >= input_bytes);
    memcpy(data,input,input_bytes); *bytes=input_bytes; input_bytes=0;
    return MICROS_OK;
}
static micros_result_t publish(micros_context_t *c, micros_handle_t handle, const uint8_t *data, uint32_t bytes)
{
    assert(c->response && handle == RESPONSE_KEY && bytes <= sizeof(output));
    memcpy(output,data,bytes); output_bytes=bytes; ++writes;
    return MICROS_OK;
}
static const struct micros_ipc_api ipc = {.ipc_open=open_port,.ipc_close=close_port,.ipc_read=read_port,.ipc_publish=publish};
static const micros_api_t api = {.struct_bytes=sizeof(micros_api_t), .abi_major=MICROS_ABI_MAJOR,
    .abi_revision=MICROS_ABI_REVISION, ._ipc=&ipc};
extern const micros_service_descriptor_t micros_descriptor;
static micros_service_args_t service;

static micros_commands_counter_Response call(micros_commands_counter_Request request)
{
    assert(!micros_commands_counter_Request_encode(&request,input,sizeof(input),&input_bytes));
    output_bytes=0;
    assert(!micros_descriptor.step(&service));
    assert(output_bytes);
    micros_commands_counter_Response response;
    assert(!micros_commands_counter_Response_decode(output,output_bytes,&response));
    assert(response.request_id == request.request_id && response.contract_id == CONTRACT_ID);
    return response;
}

/* An additional test-only handler covers bounded text, booleans and invalid output. */
micros_result_t counter_echo(const micros_service_args_t *args,
    const counter_echo_request_t *request, counter_echo_response_t *response)
{
    (void)args;
    if (request->enabled) memset(response->text,'x',sizeof(response->text));
    else memcpy(response->text,request->text,sizeof(response->text));
    response->enabled=request->enabled;
    return MICROS_OK;
}

int main(void)
{
    struct micros_context context={0};
    service=(micros_service_args_t){.struct_bytes=sizeof(service),.api=&api,.context=&context,
        .arena=calloc(1,micros_descriptor.arena_bytes),.arena_bytes=micros_descriptor.arena_bytes};
    assert(service.arena && !micros_descriptor.init(&service) && !micros_descriptor.start(&service));
    micros_commands_counter_Request request={.request_id=1,.contract_id=CONTRACT_ID,
        .which_command=micros_commands_counter_Request_set_value_tag};
    request.command.set_value.value=42;
    assert(call(request).command.set_value.value==42);
    /* Mutating the duplicate payload must still return the cached result. */
    request.command.set_value.value=43;
    assert(call(request).command.set_value.value==42);
    ++request.request_id; request.which_command=micros_commands_counter_Request_get_value_tag;
    assert(call(request).command.get_value.value==42);
    ++request.request_id; request.which_command=micros_commands_counter_Request_set_value_tag;
    request.command.set_value.value=101;
    assert(call(request).result==MICROS_ERROR_INVALID_ARGUMENT);
    ++request.request_id; request.contract_id^=1;
    assert(call(request).result==MICROS_ERROR_UNSUPPORTED);
    ++request.request_id; request.contract_id=CONTRACT_ID;
    request.which_command=micros_commands_counter_Request_echo_tag;
    request.command.echo=(counter_echo_request_t){.text="\xc3\xa9\xc3\xa9",.enabled=false};
    micros_commands_counter_Response response=call(request);
    assert(!response.result && !response.command.echo.enabled && !strcmp(response.command.echo.text,"\xc3\xa9\xc3\xa9"));
    ++request.request_id; request.command.echo.enabled=true;
    response=call(request);
    assert(response.result==MICROS_ERROR_SERVICE && response.which_command==0);
    /* Malformed protobuf has no correlatable request: ignore it without faulting. */
    unsigned previous=writes; input[0]=0xff;input_bytes=1;
    assert(!micros_descriptor.step(&service) && writes==previous);
    /* Startup discards requests left for a previous service instance. */
    ++request.request_id; request.which_command=micros_commands_counter_Request_set_value_tag;
    request.command.set_value.value=99;
    assert(!micros_commands_counter_Request_encode(&request,input,sizeof(input),&input_bytes));
    assert(!micros_descriptor.stop(&service) && !context.request && !context.response);
    memset(service.arena,0,service.arena_bytes);
    assert(!micros_descriptor.init(&service) && !micros_descriptor.start(&service));
    assert(!input_bytes);
    ++request.request_id;request.which_command=micros_commands_counter_Request_get_value_tag;
    assert(call(request).command.get_value.value==0);
    assert(!micros_descriptor.stop(&service) && !context.request && !context.response);
    free(service.arena);
    return 0;
}
