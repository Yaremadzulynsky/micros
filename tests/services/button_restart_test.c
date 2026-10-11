/* Real runtime ring, generated protobuf ports and production consumers. Workers
 * are not started: deterministic controller calls isolate restart semantics. */
#include "runtime.c"
#include "button_input.h"
#include "../../examples/services/button/generated/button_ipc.h"
#include "../../examples/services/logger/src/service.c"
#include <assert.h>
#include <stdio.h>

static uint64_t timestamp(void)
{
    uint64_t now = micros_platform_now_us();
    while (micros_platform_now_us() == now) {}
    return micros_platform_now_us();
}
static void publish(const micros_service_args_t *args, micros_handle_t port,
                    uint32_t sequence, uint64_t epoch, bool pressed)
{
    button_button_message_t message = {sequence, timestamp(), pressed, epoch};
    assert(!button_button_publish(args, port, &message));
}
static void read_press(const micros_service_args_t *args, button_input_t *input, bool expected)
{
    bool pressed = !expected;
    assert(!read_button_press(args, input, &pressed));
    assert(pressed == expected);
}
int main(int argc, char **argv)
{
    assert(argc == 2);
    micros_runtime_config_t config = micros_runtime_default_config();
    micros_runtime_t *runtime = micros_runtime_create(&config);
    micros_instance_t producer, consumer, logger;
    assert(runtime);
    assert(!micros_runtime_load(runtime, argv[1], 8, &producer));
    assert(!micros_runtime_load(runtime, argv[1], 8, &consumer));
    assert(!micros_runtime_load(runtime, argv[1], 8, &logger));
    assert(!micros_runtime_channel_create(runtime, 1, MICROS_CHANNEL_STREAM, 8, 64));
    micros_service_args_t producer_args = find_service(runtime, producer)->args;
    micros_service_args_t consumer_args = find_service(runtime, consumer)->args;
    micros_service_args_t logger_args = find_service(runtime, logger)->args;
    logger_state_t log_state = {0};
    logger_args.arena = &log_state;
    assert(!initialize(&logger_args));
    micros_handle_t publisher;
    assert(!button_button_open(&producer_args, &publisher));
    uint64_t epoch = timestamp();
    publish(&producer_args, publisher, 1, epoch, false);
    publish(&producer_args, publisher, 2, epoch, true);
    publish(&producer_args, publisher, 3, epoch, false);
    button_input_t input = {0};
    assert(!subscribe_to_button(&consumer_args, &input));
    for (unsigned i = 0; i < 3; ++i) {
        read_press(&consumer_args, &input, false); /* Retained edges are not actions. */
        assert(!step(&logger_args));
    }
    publish(&producer_args, publisher, 4, epoch, true);
    read_press(&consumer_args, &input, true);
    assert(!step(&logger_args));
    assert(!unsubscribe_from_button(&consumer_args, &input));
    assert(!micros_runtime_unload(runtime, consumer));
    assert(!micros_runtime_load(runtime, argv[1], 8, &consumer));
    consumer_args = find_service(runtime, consumer)->args;
    input = (button_input_t){0};
    assert(!subscribe_to_button(&consumer_args, &input));
    for (unsigned i = 0; i < 4; ++i) read_press(&consumer_args, &input, false);
    /* Reload publisher only, retaining consumers and channel history. */
    assert(!button_button_close(&producer_args, publisher));
    assert(!micros_runtime_unload(runtime, producer));
    assert(!micros_runtime_load(runtime, argv[1], 8, &producer));
    producer_args = find_service(runtime, producer)->args;
    assert(!button_button_open(&producer_args, &publisher));
    epoch = timestamp();
    publish(&producer_args, publisher, 1, epoch, true);
    read_press(&consumer_args, &input, false);
    assert(!step(&logger_args));
    publish(&producer_args, publisher, 2, epoch, false);
    read_press(&consumer_args, &input, false);
    assert(!step(&logger_args));
    publish(&producer_args, publisher, 3, epoch, true);
    read_press(&consumer_args, &input, true);
    assert(!step(&logger_args));
    assert(log_state.sequence == 3 && log_state.publisher_started_us == epoch);
    assert(!unsubscribe_from_button(&consumer_args, &input));
    assert(!stop(&logger_args));
    assert(!button_button_close(&producer_args, publisher));
    assert(!micros_runtime_unload(runtime, producer));
    assert(!micros_runtime_unload(runtime, consumer));
    assert(!micros_runtime_unload(runtime, logger));
    assert(!micros_runtime_channel_destroy(runtime, 1));
    assert(!micros_runtime_destroy(runtime));
    puts("PASS retained button history and independent publisher/consumer reloads");
}
