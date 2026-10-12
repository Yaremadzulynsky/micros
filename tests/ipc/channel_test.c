/* White-box access is limited to ownership/generation setup; publication and
 * reads use the synchronized SDK path exercised by real services. */
#include "runtime.c"
#include <assert.h>
#include <stdio.h>

#define TEST_KEY 1u                    /* Fixture channel key, not a compiled kernel topic. */
#define TEST_DEPTH 2u                  /* Small ring crosses overwrite boundaries quickly. */
#define TEST_PAYLOAD 64u               /* Roadmap demo payload ceiling. */
#define CONCURRENT_MESSAGES 20000u     /* Many wraps while independent readers compete. */
#define TEST_WAIT_US UINT64_C(5000000) /* Bound concurrency failures at five seconds. */

/** @brief Per-thread test state; each thread owns its counters, all channel access is locked. */
typedef struct {
    micros_context_t *context;
    micros_handle_t handle;
    uint64_t last_sequence;
    uint64_t missed;
} channel_test_worker_t;
static void *publish_many(void *argument)
{
    channel_test_worker_t *worker = argument;
    for (uint64_t sequence = 1; sequence <= CONCURRENT_MESSAGES; ++sequence) {
        uint8_t bytes[TEST_PAYLOAD];
        memset(bytes, (int)(sequence % 251),
               sizeof(bytes)); /* Prime modulus varies every byte pattern. */
        memcpy(bytes, &sequence, sizeof(sequence));
        assert(!api_ipc_publish(worker->context, worker->handle, bytes, sizeof(bytes)));
    }
    return NULL;
}
static void *read_many(void *argument)
{
    channel_test_worker_t *worker = argument;
    uint64_t deadline = micros_platform_now_us() + TEST_WAIT_US;
    while (worker->last_sequence < CONCURRENT_MESSAGES) {
        assert(micros_platform_now_us() < deadline);
        uint8_t bytes[TEST_PAYLOAD];
        uint32_t size;
        micros_message_info_t info;
        micros_result_t result =
            api_ipc_read(worker->context, worker->handle, bytes, sizeof(bytes), &size, &info);
        if (result == MICROS_ERROR_EMPTY)
            continue;
        if (result == MICROS_ERROR_MESSAGES_MISSED) {
            worker->missed += info.messages_missed;
            continue;
        }
        assert(!result && size == sizeof(bytes));
        uint64_t sequence;
        memcpy(&sequence, bytes, sizeof(sequence));
        assert(sequence == info.sequence && sequence > worker->last_sequence);
        for (size_t byte = sizeof(sequence); byte < sizeof(bytes); ++byte)
            assert(bytes[byte] == sequence % 251);
        worker->last_sequence = sequence;
    }
    return NULL;
}
int main(int argc, char **argv)
{
    /* Host has no PSRAM: never silently allocate an external request internally. */
    assert(micros_platform_arena_allocate(16, 16, 1) == NULL);
    assert(argc == 2);
    micros_runtime_config_t config = micros_runtime_default_config();
    micros_runtime_t *runtime = micros_runtime_create(&config);
    assert(runtime);
    micros_instance_t producer, consumer;
    assert(!micros_runtime_load(runtime, argv[1], 8, &producer));
    assert(!micros_runtime_load(runtime, argv[1], 8, &consumer));
    micros_context_t *publisher_context = &find_service(runtime, producer)->context;
    micros_context_t *subscriber_context = &find_service(runtime, consumer)->context;
    assert(micros_runtime_channel_create(runtime, TEST_KEY, MICROS_CHANNEL_LATEST, TEST_DEPTH,
                                         TEST_PAYLOAD) == MICROS_ERROR_INVALID_ARGUMENT);
    runtime->config.channel_bytes = TEST_DEPTH * TEST_PAYLOAD - 1;
    assert(micros_runtime_channel_create(runtime, TEST_KEY, MICROS_CHANNEL_STREAM, TEST_DEPTH,
                                         TEST_PAYLOAD) == MICROS_ERROR_CAPACITY);
    runtime->config.channel_bytes = MICROS_CHANNEL_POOL_BYTES;
    assert(!micros_runtime_channel_create(runtime, TEST_KEY, MICROS_CHANNEL_STREAM, TEST_DEPTH,
                                          TEST_PAYLOAD));
    assert(micros_runtime_channel_create(runtime, TEST_KEY, MICROS_CHANNEL_STREAM, TEST_DEPTH,
                                         TEST_PAYLOAD) == MICROS_ERROR_BUSY);
    micros_handle_t publisher, first, second;
    assert(!api_ipc_open(publisher_context, TEST_KEY, MICROS_IPC_PUBLISH, &publisher));
    assert(!api_ipc_open(subscriber_context, TEST_KEY, MICROS_IPC_SUBSCRIBE, &first));
    assert(!api_ipc_open(subscriber_context, TEST_KEY, MICROS_IPC_SUBSCRIBE, &second));
    uint8_t output[TEST_PAYLOAD];
    uint32_t bytes;
    micros_message_info_t info;
    assert(api_ipc_read(subscriber_context, first, output, sizeof(output), &bytes, &info) ==
           MICROS_ERROR_EMPTY);
    assert(api_ipc_publish(subscriber_context, publisher, (const uint8_t *)"x", 1) ==
           MICROS_ERROR_STALE_HANDLE);
    assert(api_ipc_read(publisher_context, first, output, sizeof(output), &bytes, &info) ==
           MICROS_ERROR_STALE_HANDLE);
    assert(api_ipc_publish(publisher_context, publisher, output, TEST_PAYLOAD + 1) ==
           MICROS_ERROR_CAPACITY);
    assert(!api_ipc_publish(publisher_context, publisher, (const uint8_t *)"one", 3));
    assert(api_ipc_read(subscriber_context, first, output, 2, &bytes, &info) ==
               MICROS_ERROR_CAPACITY &&
           bytes == 3);
    assert(!api_ipc_read(subscriber_context, first, output, sizeof(output), &bytes, &info) &&
           info.sequence == 1);
    assert(!api_ipc_read(subscriber_context, second, output, sizeof(output), &bytes, &info) &&
           info.sequence == 1);
    micros_channel_status_t retained_status;
    assert(!micros_runtime_channel_status(runtime, 0, &retained_status));
    assert(retained_status.backlog == 0 && retained_status.retained_bytes == 3);
    for (unsigned sequence = 2; sequence <= 5; ++sequence)
        assert(!api_ipc_publish(publisher_context, publisher, (const uint8_t *)&sequence,
                                sizeof(sequence)));
    assert(api_ipc_read(subscriber_context, first, output, sizeof(output), &bytes, &info) ==
           MICROS_ERROR_MESSAGES_MISSED);
    assert(info.messages_missed == 2 && info.sequence == 4 && bytes == 0);
    micros_channel_status_t telemetry;
    assert(!micros_runtime_channel_status(runtime, 0, &telemetry));
    assert(telemetry.published == 5 && telemetry.missed == 2);
    assert(telemetry.backlog == TEST_DEPTH && telemetry.subscribers == 2);
    assert(telemetry.publishers == 1);
    assert(telemetry.retained_bytes == TEST_DEPTH * sizeof(unsigned));
    micros_runtime_usage_t allocation = micros_runtime_usage(runtime);
    assert(allocation.channel_payload_capacity == TEST_DEPTH * TEST_PAYLOAD);
    assert(allocation.channel_storage_bytes == sizeof(micros_channel_t) * MICROS_CHANNEL_CAPACITY + TEST_DEPTH * TEST_PAYLOAD + sizeof(micros_coord_channel_t));
    assert(allocation.kernel_metadata_bytes >= allocation.channel_storage_bytes);
    assert(!api_ipc_read(subscriber_context, first, output, sizeof(output), &bytes, &info) &&
           info.sequence == 4);
    assert(api_ipc_read(subscriber_context, second, output, sizeof(output), &bytes, &info) ==
           MICROS_ERROR_MESSAGES_MISSED);
    assert(!micros_runtime_channel_destroy(runtime, TEST_KEY));
    assert(
        !micros_runtime_channel_create(runtime, TEST_KEY, MICROS_CHANNEL_LATEST, 1, TEST_PAYLOAD));
    assert(!micros_runtime_channel_status(runtime, 0, &telemetry));
    assert(!telemetry.published && !telemetry.missed && !telemetry.backlog);
    assert(!telemetry.retained_bytes);
    assert(api_ipc_publish(publisher_context, publisher, output, 1) == MICROS_ERROR_STALE_HANDLE);
    assert(api_ipc_read(subscriber_context, first, output, sizeof(output), &bytes, &info) ==
           MICROS_ERROR_STALE_HANDLE);
    assert(!api_ipc_close(publisher_context, publisher));
    assert(!api_ipc_close(subscriber_context, first));
    assert(!api_ipc_close(subscriber_context, second));
    assert(!api_ipc_open(publisher_context, TEST_KEY, MICROS_IPC_PUBLISH, &publisher));
    assert(!api_ipc_open(subscriber_context, TEST_KEY, MICROS_IPC_SUBSCRIBE, &first));
    for (unsigned sequence = 0; sequence < 3; ++sequence)
        assert(!api_ipc_publish(publisher_context, publisher, output, 0));
    assert(!api_ipc_read(subscriber_context, first, NULL, 0, &bytes, &info) && info.sequence == 3 &&
           info.messages_missed == 2);
    assert(api_ipc_read(subscriber_context, first, NULL, 0, &bytes, &info) == MICROS_ERROR_EMPTY);
    runtime->channels[0].sequence = UINT64_MAX - 1;
    assert(api_ipc_publish(publisher_context, publisher, NULL, 0) == MICROS_ERROR_CAPACITY);
    assert(!api_ipc_close(publisher_context, publisher));
    assert(!api_ipc_close(subscriber_context, first));
    assert(!micros_runtime_channel_destroy(runtime, TEST_KEY));
    runtime->channels[0].generation = UINT32_MAX;
    assert(!micros_runtime_channel_create(runtime, TEST_KEY, MICROS_CHANNEL_STREAM, TEST_DEPTH,
                                          TEST_PAYLOAD));
    assert(!micros_runtime_channel_destroy(runtime, TEST_KEY));
    assert(!runtime->channels[0].generation);
    assert(!micros_runtime_channel_create(runtime, TEST_KEY, MICROS_CHANNEL_STREAM, TEST_DEPTH,
                                          TEST_PAYLOAD));
    assert(!api_ipc_open(publisher_context, TEST_KEY, MICROS_IPC_PUBLISH, &publisher));
    assert(!api_ipc_open(subscriber_context, TEST_KEY, MICROS_IPC_SUBSCRIBE, &first));
    assert(!api_ipc_open(subscriber_context, TEST_KEY, MICROS_IPC_SUBSCRIBE, &second));
    channel_test_worker_t writer = {publisher_context, publisher, 0, 0};
    channel_test_worker_t readers[] = {{subscriber_context, first, 0, 0},
                                       {subscriber_context, second, 0, 0}};
    size_t stack = micros_platform_stack_bytes(MICROS_M1_STACK_BYTES);
    micros_platform_task_t *reader_tasks[] = {
        micros_platform_task_create(read_many, &readers[0], stack),
        micros_platform_task_create(read_many, &readers[1], stack)};
    micros_platform_task_t *writer_task = micros_platform_task_create(publish_many, &writer, stack);
    assert(reader_tasks[0] && reader_tasks[1] && writer_task);
    micros_platform_task_join(writer_task);
    micros_platform_task_join(reader_tasks[0]);
    micros_platform_task_join(reader_tasks[1]);
    assert(readers[0].last_sequence == CONCURRENT_MESSAGES &&
           readers[1].last_sequence == CONCURRENT_MESSAGES);
    assert(!api_ipc_close(publisher_context, publisher));
    assert(!api_ipc_close(subscriber_context, first));
    assert(!api_ipc_close(subscriber_context, second));
    assert(!micros_runtime_unload(runtime, producer));
    assert(!micros_runtime_unload(runtime, consumer));
    assert(!micros_runtime_channel_destroy(runtime, TEST_KEY));
    micros_runtime_usage_t usage = micros_runtime_usage(runtime);
    assert(!usage.channels && !usage.channel_bytes && !usage.live_handles &&
           !usage.loaded_services);
    assert(!usage.channel_payload_capacity);
    assert(usage.channel_storage_bytes == sizeof(runtime->channels));
    /* Runtime destruction also owns any remaining channel buffers. */
    assert(!micros_runtime_channel_create(runtime, 99, MICROS_CHANNEL_STREAM, 3, 17));
    assert(micros_runtime_usage(runtime).channel_payload_capacity == 51);
    assert(!micros_runtime_destroy(runtime));
    puts("PASS stream/latest, independent cursors, loss, capacity, owner/generation rejection, "
         "sequence exhaustion, 20000 concurrent publications without torn payloads");
}
