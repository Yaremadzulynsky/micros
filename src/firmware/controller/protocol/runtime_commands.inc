/* Low-level lifecycle commands are available on every platform. The deployment
 * controller and interactive tooling use the same runtime and admission rules. */
#define CONTROL_PATH_BYTES 4096u
static int decode_path(const char *encoded, char *path)
{
    size_t size = strlen(encoded);
    if (size % 2 || size / 2 >= CONTROL_PATH_BYTES)
        return 0;
    for (size_t index = 0; index < size / 2; ++index) {
        int hi=micros_ipc_hex(encoded[index*2]),lo=micros_ipc_hex(encoded[index*2+1]);
        if(hi<0 || lo<0 || !(hi|lo))return 0;
        path[index]=(char)((hi<<4)|lo);
    }
    path[size / 2] = 0;
    return 1;
}

static int runtime_command_body(char *line,uint32_t *publish_masks)
{
micros_result_t result = MICROS_ERROR_INVALID_ARGUMENT;
uint64_t instance = 0;
unsigned key, policy, depth, payload, handles, timers, gpio, publishes, subscribes;
if (sscanf(line, "CHANNEL %u %u %u %u", &key, &policy, &depth, &payload) == 4)
    result = micros_runtime_channel_create(runtime, key, policy, depth, payload);
else if (sscanf(line, "DESTROY_CHANNEL %u", &key) == 1)
    result = micros_runtime_channel_destroy(runtime, key);
else if (!strcmp(line, "START_GRAPH\n"))
    result = micros_application_start(runtime, instances, publish_masks, instance_count,
                                       micros_runtime_default_config().lifecycle_timeout_us);
else if (!strncmp(line, "LOAD ", 5)) {
    char *encoded=line+5, *fields=strchr(encoded,' ');
    if (!fields) { printf("{\"result\":-1}\n");return 1; }
    *fields++=0;
    size_t path_bytes=strlen(encoded)/2+1;
    char *path=malloc(path_bytes);
    if (!path) { printf("{\"result\":-5}\n");return 1; }
    if (sscanf(fields, "%u %u %u %u %u", &handles, &timers, &gpio,
               &publishes, &subscribes) == 5 &&
        decode_path(encoded, path)) {
        result = micros_runtime_load(runtime, path, handles, &instance);
        if (!result) {
            micros_resource_policy_t permissions = {timers, gpio, publishes, subscribes};
            result = micros_runtime_set_policy(runtime, instance, &permissions);
            if (result) micros_runtime_unload(runtime, instance);
            else {
                /* Replace an unloaded slot when an individual service is reloaded. */
                unsigned index = 0;
                for (; index < instance_count; ++index) {
                    micros_service_status_t status;
                    if (micros_runtime_status(runtime, instances[index], &status)) break;
                }
                if (index == instance_count) ++instance_count;
                instances[index] = instance;
                publish_masks[index] = publishes;
            }
        }
    }
    free(path);
} else if (!strncmp(line, "CONFIGURE ", 10)) {
    char encoded[MICROS_CONFIG_MAX_BYTES * 2 + 1];
    uint8_t data[MICROS_CONFIG_MAX_BYTES];
    int consumed = 0;
    if (sscanf(line, "CONFIGURE %" SCNu64 " %512s%n", &instance, encoded, &consumed) == 2 &&
        !strcmp(line + consumed, "\n")) {
        size_t length = strlen(encoded);
        int valid = length % 2 == 0 && length <= sizeof(data) * 2;
        for (size_t index = 0; valid && index < length; ++index)
            valid = (encoded[index] >= '0' && encoded[index] <= '9') ||
                    (encoded[index] >= 'a' && encoded[index] <= 'f');
        for (size_t index = 0; valid && index < length / 2; ++index) {
            unsigned value;
            if (sscanf(encoded + index * 2, "%2x", &value) != 1)
                valid = 0;
            else
                data[index] = (uint8_t)value;
        }
        if (valid)
            result = micros_runtime_set_config(runtime, instance, data, length / 2);
    }
} else if (sscanf(line, "START %" SCNu64, &instance) == 1)
    result = micros_runtime_start(runtime, instance);
else if (sscanf(line, "STOP %" SCNu64, &instance) == 1)
    result = micros_runtime_stop(runtime, instance);
else if (sscanf(line, "UNLOAD %" SCNu64, &instance) == 1)
    result = micros_runtime_unload(runtime, instance);
else if (sscanf(line, "STATUS %" SCNu64, &instance) == 1) {
    micros_service_status_t status;
    result = micros_runtime_status(runtime, instance, &status);
    if (!result) {
        printf("{\"result\":0,\"state\":\"%s\",\"service_result\":%d,\"handles\":%u,"
               "\"steps\":%" PRIu64 ",\"callbacks\":%" PRIu64
               ",\"reboot_required\":%u,\"arena_bytes\":%u,\"arena_alignment\":%u,\"stack_"
               "bytes\":%u}\n",
               micros_runtime_state_name(status.state), (int)status.result, (unsigned)status.owned_handles,
               status.completed_steps, status.completed_callbacks, (unsigned)status.reboot_required,
               (unsigned)status.arena_bytes, (unsigned)status.arena_alignment, (unsigned)status.stack_bytes);
        return 1;
    }
} else if (!strcmp(line, "USAGE\n")) {
    micros_runtime_usage_t usage = micros_runtime_usage(runtime);
    printf("{\"result\":0,\"services\":%u,\"handles\":%u,\"reserved_handles\":%u,\"tasks\":"
           "%u,\"channels\":%u,\"channel_bytes\":%zu,\"image_bytes\":%zu,\"arena_bytes\":%"
           "zu,\"requested_stack_bytes\":%zu,\"host_stack_bytes\":%zu,\"kernel_metadata_"
           "bytes\":%zu,\"reboot_required\":%u}\n",
           (unsigned)usage.loaded_services, (unsigned)usage.live_handles, (unsigned)usage.reserved_handles,
           (unsigned)usage.live_tasks, (unsigned)usage.channels, usage.channel_bytes, usage.image_bytes,
           usage.arena_bytes, usage.stack_bytes, usage.platform_stack_bytes,
           usage.kernel_metadata_bytes, (unsigned)usage.reboot_required);
    return 1;
} else if (!strcmp(line, "QUIT\n")) {
    result = micros_runtime_destroy(runtime);
    printf("{\"result\":%d}\n", (int)result);
    return 2;
}
printf("{\"result\":%d,\"instance\":%" PRIu64 "}\n", (int)result, instance);
return 1;
}

static __attribute__((noinline)) int runtime_command(char *input)
{
    int recognized=!strncmp(input,"CHANNEL ",8) || !strncmp(input,"DESTROY_CHANNEL ",16) ||
        !strcmp(input,"START_GRAPH") || !strncmp(input,"LOAD ",5) ||
        !strncmp(input,"CONFIGURE ",10) || !strncmp(input,"START ",6) ||
        !strncmp(input,"STOP ",5) || !strncmp(input,"UNLOAD ",7) ||
        !strncmp(input,"STATUS ",7) || !strcmp(input,"USAGE") || !strcmp(input,"QUIT");
    /* CONFIG <bank> <binary length> belongs to deployment. Runtime payloads
     * use CONFIGURE to keep one unambiguous command grammar. */
    if (!recognized || !strncmp(input,"CONFIG ",7)) return 0;
    if (!runtime) {
        micros_runtime_config_t config=micros_runtime_default_config();
        runtime=micros_runtime_create(&config);
        if (!runtime) { printf("{\"result\":-5}\n");return 1; }
    }
    static uint32_t publish_masks[MICROS_RUNTIME_SERVICE_CAPACITY];
    size_t length=strlen(input);
    char *line=malloc(length+2);
    if (!line) { printf("{\"result\":-5}\n");return 1; }
    memcpy(line,input,length);line[length]='\n';line[length+1]=0;
    int handled=runtime_command_body(line,publish_masks);
    free(line);return handled;
}
