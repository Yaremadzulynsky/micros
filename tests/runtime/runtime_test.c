/* Include the implementation in this test translation unit to exercise owner
 * checks and generation exhaustion without exposing mutation hooks in the API.
 * All lifecycle tests still execute independently compiled native images. */
#include "runtime.c"
#include <assert.h>
#include <stdio.h>

/* Poll for at most two seconds; fault hooks use a deliberately short 30 ms
 * deadline, while cooperative overlap tests allow 500 ms for a 50 ms hold. */
#define TEST_WAIT_US UINT64_C(2000000)
#define TEST_WORK_US UINT64_C(500000)
#define FAULT_BUDGET_US UINT64_C(30000)
#define POLL_US UINT64_C(1000)
#define RELOAD_CYCLES 20u   /* Enough to exercise reuse/generations beyond table capacity. */
#define PATH_CAPACITY 4096u /* Local test paths, checked for truncation below. */
static char image_path[PATH_CAPACITY];
static const char *fixture_path(const char *directory, const char *name)
{
    int length = snprintf(image_path, sizeof(image_path), "%s/fixture_%s.mimg", directory, name);
    assert(length > 0 && (size_t)length < sizeof(image_path));
    return image_path;
}
static void pause_poll(micros_runtime_t *runtime)
{
    micros_platform_lock(runtime->sync);
    micros_platform_wait(runtime->sync, micros_platform_now_us() + POLL_US);
    micros_platform_unlock(runtime->sync);
}
static micros_service_status_t wait_progress(micros_runtime_t *runtime, micros_instance_t instance,
                                             unsigned writes, unsigned callbacks)
{
    uint64_t deadline = micros_platform_now_us() + TEST_WAIT_US;
    micros_service_status_t status;
    do {
        assert(micros_runtime_status(runtime, instance, &status) == MICROS_OK);
        if ((status.diagnostic_writes >= writes && status.completed_callbacks >= callbacks) ||
            status.state == MICROS_STATE_FAILED)
            return status;
        pause_poll(runtime);
    } while (micros_platform_now_us() < deadline);
    assert(!"service did not make expected progress");
    return status;
}
static void baseline(micros_runtime_t *runtime)
{
    micros_runtime_usage_t usage = micros_runtime_usage(runtime);
    assert(!usage.loaded_services && !usage.live_handles && !usage.reserved_handles &&
           !usage.live_tasks && !usage.active_callbacks && !usage.arena_bytes &&
           !usage.image_bytes && !usage.arena_storage_bytes && !usage.stack_bytes &&
           !usage.platform_stack_bytes && !usage.reboot_required);
}
static micros_result_t no_callback(const micros_service_args_t *args, micros_handle_t timer,
                                   void *user_data)
{
    (void)args;
    (void)timer;
    (void)user_data;
    return MICROS_OK;
}
static void test_ownership(const char *directory)
{
    micros_runtime_config_t config = micros_runtime_default_config();
    micros_runtime_t *runtime = micros_runtime_create(&config);
    assert(runtime);
    micros_instance_t first, second;
    assert(!micros_runtime_load(runtime, fixture_path(directory, "NORMAL"), 8, &first));
    assert(!micros_runtime_load(runtime, fixture_path(directory, "NORMAL"), 8, &second));
    service_slot_t *owner = find_service(runtime, first), *foreign = find_service(runtime, second);
    micros_handle_t gpio, timer, replacement;
    assert(!api_gpio_open(&owner->context, 0, &gpio));
    uint32_t level = 0;
    assert(api_gpio_read(&foreign->context, gpio, &level) == MICROS_ERROR_STALE_HANDLE);
    assert(api_gpio_read_analog(&foreign->context, gpio, &level) == MICROS_ERROR_STALE_HANDLE);
    level = 1234;
    assert(api_gpio_read_analog(&owner->context, gpio, &level) == MICROS_ERROR_UNSUPPORTED);
    assert(level == 1234);
    assert(api_gpio_read_analog(&owner->context, gpio, NULL) == MICROS_ERROR_INVALID_ARGUMENT);
    assert(api_gpio_write(&foreign->context, gpio, 1) == MICROS_ERROR_STALE_HANDLE);
    assert(api_gpio_close(&foreign->context, gpio) == MICROS_ERROR_STALE_HANDLE);
    assert(api_gpio_open(&foreign->context, 0, &replacement) == MICROS_ERROR_BUSY);
    assert(!api_timer_open(&owner->context, POLL_US, 0, no_callback, NULL, &timer));
    assert(api_timer_close(&foreign->context, timer) == MICROS_ERROR_STALE_HANDLE);
    assert(!api_gpio_write(&owner->context, gpio, 1));
    assert(!api_gpio_read(&owner->context, gpio, &level) && level == 1);
    assert(api_gpio_write(&owner->context, gpio, 2) == MICROS_ERROR_INVALID_ARGUMENT);
    assert(!api_gpio_close(&owner->context, gpio));
    assert(!api_gpio_open(&foreign->context, 0, &replacement));
    assert(!api_gpio_read(&foreign->context, replacement, &level) && level == 0);
    assert(!api_gpio_close(&foreign->context, replacement));
    assert(!api_timer_close(&owner->context, timer));
    /* Force the otherwise impractical last generation, then prove retirement. */
    runtime->resources[0].generation = UINT32_MAX;
    assert(!api_gpio_open(&owner->context, 0, &gpio));
    assert(!api_gpio_close(&owner->context, gpio));
    assert(runtime->usage.retired_handles == 1);
    assert(!api_gpio_open(&owner->context, 0, &replacement));
    assert(gpio != replacement &&
           api_gpio_read(&owner->context, gpio, &level) == MICROS_ERROR_STALE_HANDLE);
    assert(!api_gpio_close(&owner->context, replacement));
    assert(!micros_runtime_unload(runtime, first));
    assert(!micros_runtime_unload(runtime, second));
    runtime->services[0].generation = UINT32_MAX;
    assert(!micros_runtime_load(runtime, fixture_path(directory, "NORMAL"), 0, &first));
    assert(!micros_runtime_unload(runtime, first));
    assert(runtime->usage.retired_services == 1);
    assert(!micros_runtime_load(runtime, fixture_path(directory, "NORMAL"), 0, &second));
    assert(first != second);
    assert(micros_runtime_start(runtime, first) == MICROS_ERROR_STALE_HANDLE);
    assert(!micros_runtime_unload(runtime, second));
    baseline(runtime);
    assert(!micros_runtime_destroy(runtime));
    puts("PASS owner checks, GPIO conflicts, stale resources/instances, generation exhaustion");
}
static void test_configuration_storage(const char *directory)
{
    micros_runtime_config_t config = micros_runtime_default_config();
    micros_runtime_t *runtime = micros_runtime_create(&config);
    micros_instance_t instance;
    assert(!micros_runtime_load(runtime, fixture_path(directory, "NORMAL"), 2, &instance));
    size_t metadata = micros_runtime_usage(runtime).kernel_metadata_bytes;
    uint8_t settings[MICROS_CONFIG_MAX_BYTES];
    memset(settings, 0x37, sizeof(settings));
    assert(!micros_runtime_set_config(runtime, instance, settings, sizeof(settings)));
    service_slot_t *slot = find_service(runtime, instance);
    settings[0] = 0;
    assert(slot->args.config_data[0] == 0x37);
    assert(micros_runtime_usage(runtime).kernel_metadata_bytes == metadata + sizeof(settings));
    assert(!micros_runtime_set_config(runtime, instance, slot->args.config_data, 2));
    assert(slot->args.config_data[0] == 0x37 && slot->args.config_bytes == 2);
    assert(micros_runtime_usage(runtime).kernel_metadata_bytes == metadata + 2);
    assert(!micros_runtime_set_config(runtime, instance, NULL, 0));
    assert(!slot->args.config_data && !slot->args.config_bytes);
    assert(micros_runtime_usage(runtime).kernel_metadata_bytes == metadata);
    assert(!micros_runtime_unload(runtime, instance));
    assert(!micros_runtime_destroy(runtime));
}

static void test_individual_restart(const char *directory)
{
    micros_runtime_config_t config = micros_runtime_default_config();
    config.work_timeout_us = TEST_WORK_US;
    micros_runtime_t *runtime = micros_runtime_create(&config);
    micros_instance_t target = 0, peer;
    micros_resource_policy_t policy = {1, 1, 1, 1};
    const uint8_t settings[] = {7, 9};
    assert(!micros_runtime_load(runtime, fixture_path(directory, "NORMAL_PEER"), 2, &peer));
    assert(!micros_runtime_start(runtime, peer));
    micros_service_status_t before = wait_progress(runtime, peer, 0, 2);
    assert(!micros_runtime_channel_create(runtime, 1, MICROS_CHANNEL_STREAM, 8, 64));
    for (unsigned cycle = 0; cycle < RELOAD_CYCLES; ++cycle) {
        micros_instance_t previous = target;
        assert(!micros_runtime_restart(runtime, &target, fixture_path(directory, "NORMAL"),
                                       2, &policy, settings, sizeof(settings)));
        assert(target && target != previous);
        assert(wait_progress(runtime, target, 0, 2).state == MICROS_STATE_RUNNING);
        service_slot_t *slot = find_service(runtime, target);
        assert(slot->policy_enabled && slot->policy.gpio_mask == 1);
        assert(slot->args.config_bytes == sizeof(settings));
        assert(!memcmp(slot->args.config_data, settings, sizeof(settings)));
        assert(wait_progress(runtime, peer, 0, (unsigned)before.completed_callbacks + 2).state == MICROS_STATE_RUNNING);
        assert(micros_runtime_usage(runtime).loaded_services == 2);
        assert(micros_runtime_usage(runtime).channels == 1);
    }
    /* Recover a normal lifecycle failure without touching the peer. */
    assert(!micros_runtime_restart(runtime, &target, fixture_path(directory, "FAIL_INIT"),
                                   2, &policy, settings, sizeof(settings)));
    assert(wait_progress(runtime, target, 99, 99).state == MICROS_STATE_FAILED);
    assert(!micros_runtime_restart(runtime, &target, fixture_path(directory, "NORMAL"),
                                   2, &policy, settings, sizeof(settings)));
    assert(wait_progress(runtime, target, 0, 2).state == MICROS_STATE_RUNNING);
    assert(micros_runtime_restart(runtime, &target, "/missing/service.mimg",
                                  2, &policy, settings, sizeof(settings)));
    assert(!target);
    assert(!micros_runtime_restart(runtime, &target, fixture_path(directory, "NORMAL"),
                                   2, &policy, settings, sizeof(settings)));
    assert(wait_progress(runtime, target, 0, 2).state == MICROS_STATE_RUNNING);
    micros_service_status_t after;
    assert(!micros_runtime_status(runtime, peer, &after));
    assert(after.state == MICROS_STATE_RUNNING && after.completed_callbacks > before.completed_callbacks);
    assert(!micros_runtime_stop(runtime, target));
    assert(!micros_runtime_unload(runtime, target));
    assert(!micros_runtime_stop(runtime, peer));
    assert(!micros_runtime_unload(runtime, peer));
    assert(!micros_runtime_channel_destroy(runtime, 1));
    baseline(runtime);
    assert(!micros_runtime_destroy(runtime));
    puts("PASS individual restart, fresh image state, configuration, peer continuity and failed-load retry");
}

static void test_manifest_policy(const char *directory)
{
    micros_runtime_config_t config = micros_runtime_default_config();
    micros_runtime_t *runtime = micros_runtime_create(&config);
    micros_instance_t instance;
    assert(!micros_runtime_load(runtime, fixture_path(directory, "NORMAL"), 8, &instance));
    /* Stack default is not an admission floor; validate without executing tiny stacks. */
    micros_service_descriptor_t descriptor = *find_service(runtime, instance)->descriptor;
    const uint32_t budgets[] = {1, 1024, 2048, 4095, 4096, 16384};
    for (size_t index = 0; index < sizeof(budgets) / sizeof(budgets[0]); ++index) {
        descriptor.stack_bytes = budgets[index];
        assert(!micros_descriptor_validate(&descriptor, descriptor.target));
    }
    descriptor.stack_bytes = 0;
    assert(micros_descriptor_validate(&descriptor, descriptor.target));
    descriptor.stack_bytes = 16385;
    assert(micros_descriptor_validate(&descriptor, descriptor.target));
    /* Permit only line zero and one timer; deny all undeclared IPC channels. */
    micros_resource_policy_t policy = {.timer_limit = 1, .gpio_mask = 1};
    assert(!micros_runtime_set_policy(runtime, instance, &policy));
    micros_context_t *context = &find_service(runtime, instance)->context;
    micros_handle_t gpio, timer, extra;
    assert(api_gpio_open(context, 1, &extra) == MICROS_ERROR_UNSUPPORTED);
    assert(!api_gpio_open(context, 0, &gpio));
    assert(!api_timer_open(context, POLL_US, 0, no_callback, NULL, &timer));
    assert(api_timer_open(context, POLL_US, 0, no_callback, NULL, &extra) == MICROS_ERROR_CAPACITY);
    assert(api_ipc_open(context, 1, MICROS_IPC_PUBLISH, &extra) == MICROS_ERROR_UNSUPPORTED);
    micros_service_status_t telemetry;
    assert(!micros_runtime_status(runtime, instance, &telemetry));
    assert(telemetry.gpio_granted == 1 && telemetry.gpio_open == 1);
    assert(telemetry.timers_open == 1 && telemetry.timer_limit == 1);
    assert(telemetry.owned_handles == 2 && telemetry.handle_limit == 8);
    assert(micros_runtime_set_policy(runtime, instance, &policy) == MICROS_ERROR_STATE);
    assert(!api_gpio_close(context, gpio));
    assert(!api_timer_close(context, timer));
    assert(!micros_runtime_status(runtime, instance, &telemetry));
    assert(!telemetry.timers_open && !telemetry.gpio_open && !telemetry.owned_handles);
    assert(telemetry.gpio_granted == 1); /* Closing releases ownership, not permission. */
    assert(!micros_runtime_unload(runtime, instance));
    baseline(runtime);
    assert(!micros_runtime_destroy(runtime));
    puts("PASS manifest-derived GPIO/timer/IPC capability enforcement");
}
static void test_admission(const char *directory)
{
    for (unsigned resource = 0; resource < 5; ++resource) {
        micros_runtime_config_t config = micros_runtime_default_config();
        /* Each case independently removes one admission class's capacity. */
        if (resource == 0)
            config.image_bytes = 0;
        if (resource == 1)
            config.arena_bytes = 0;
        if (resource == 2)
            config.stack_bytes = 0;
        if (resource == 3)
            config.platform_stack_bytes = 0;
        if (resource == 4)
            config.handle_count = 0;
        micros_runtime_t *runtime = micros_runtime_create(&config);
        assert(runtime);
        micros_instance_t instance;
        assert(micros_runtime_load(runtime, fixture_path(directory, "NORMAL"), 1, &instance) ==
               MICROS_ERROR_CAPACITY);
        baseline(runtime);
        assert(!micros_runtime_destroy(runtime));
    }
    micros_runtime_config_t config = micros_runtime_default_config();
    micros_runtime_t *runtime = micros_runtime_create(&config);
    micros_instance_t instances[MICROS_RUNTIME_SERVICE_CAPACITY], extra;
    for (unsigned slot = 0; slot < MICROS_RUNTIME_SERVICE_CAPACITY; ++slot)
        assert(!micros_runtime_load(runtime, fixture_path(directory, "NORMAL"),
                                    MICROS_RUNTIME_HANDLES_PER_SERVICE, &instances[slot]));
    assert(micros_runtime_load(runtime, fixture_path(directory, "NORMAL"), 0, &extra) ==
           MICROS_ERROR_CAPACITY);
    assert(micros_runtime_destroy(runtime) == MICROS_ERROR_STATE);
    for (unsigned slot = 0; slot < MICROS_RUNTIME_SERVICE_CAPACITY; ++slot)
        assert(!micros_runtime_unload(runtime, instances[slot]));
    baseline(runtime);
    assert(!micros_runtime_destroy(runtime));
    assert(!fits(SIZE_MAX, 1, SIZE_MAX));
    puts("PASS image/arena/requested-stack/host-stack/handle admission and table capacity");
}
static void test_cycles(const char *directory)
{
    micros_runtime_config_t config = micros_runtime_default_config();
    config.work_timeout_us = TEST_WORK_US;
    micros_runtime_t *runtime = micros_runtime_create(&config);
    for (unsigned cycle = 0; cycle < RELOAD_CYCLES; ++cycle) {
        micros_instance_t instance;
        assert(
            !micros_runtime_load(runtime, fixture_path(directory, "HANDLE_CHECKS"), 8, &instance));
        assert(!micros_runtime_stop(runtime, instance)); /* Loaded stop is a no-op. */
        assert(!micros_runtime_start(runtime, instance));
        assert(micros_runtime_start(runtime, instance) == MICROS_ERROR_STATE);
        assert(micros_runtime_unload(runtime, instance) == MICROS_ERROR_STATE);
        micros_service_status_t status = wait_progress(runtime, instance, 0, 2);
        assert(status.state == MICROS_STATE_RUNNING && !status.result);
        assert(!micros_runtime_stop(runtime, instance));
        assert(!micros_runtime_stop(runtime, instance));
        assert(!micros_runtime_status(runtime, instance, &status));
        assert(status.state == MICROS_STATE_STOPPED && status.owned_handles == 0);
        uint64_t callbacks = status.completed_callbacks;
        pause_poll(runtime);
        assert(!micros_runtime_status(runtime, instance, &status));
        assert(callbacks == status.completed_callbacks);
        assert(micros_runtime_start(runtime, instance) == MICROS_ERROR_STATE);
        assert(!micros_runtime_unload(runtime, instance));
        assert(micros_runtime_start(runtime, instance) == MICROS_ERROR_STALE_HANDLE);
        baseline(runtime);
    }
    assert(!micros_runtime_destroy(runtime));
    puts("PASS 20 independent reloads, zeroed state, legal transitions, handle exhaustion and "
         "callback quiescence");
}
static void test_concurrent_services(const char *directory)
{
    micros_runtime_config_t config = micros_runtime_default_config();
    config.work_timeout_us = TEST_WORK_US;
    micros_runtime_t *runtime = micros_runtime_create(&config);
    micros_instance_t first, second;
    assert(!micros_runtime_load(runtime, fixture_path(directory, "NORMAL"), 2, &first));
    assert(!micros_runtime_load(runtime, fixture_path(directory, "NORMAL_PEER"), 2, &second));
    assert(!micros_runtime_start(runtime, first));
    assert(!micros_runtime_start(runtime, second));
    assert(wait_progress(runtime, first, 0, 2).state == MICROS_STATE_RUNNING);
    micros_service_status_t status = wait_progress(runtime, second, 0, 2);
    assert(status.state == MICROS_STATE_RUNNING);
    assert(!micros_runtime_pause(runtime));
    micros_service_status_t frozen, still;
    assert(!micros_runtime_status(runtime, second, &frozen));
    for (unsigned i = 0; i < 10; ++i) pause_poll(runtime);
    assert(!micros_runtime_status(runtime, second, &still));
    assert(still.completed_steps == frozen.completed_steps &&
           still.completed_callbacks == frozen.completed_callbacks &&
           still.owned_handles == frozen.owned_handles && still.state == MICROS_STATE_RUNNING);
    assert(micros_runtime_pause(runtime) == MICROS_ERROR_STATE);
    micros_runtime_resume(runtime);
    assert(wait_progress(runtime, second, 0, (unsigned)frozen.completed_callbacks + 2).state == MICROS_STATE_RUNNING);
    assert(!micros_runtime_stop(runtime, first));
    assert(!micros_runtime_unload(runtime, first));
    assert(wait_progress(runtime, second, 0, (unsigned)status.completed_callbacks + 2).state ==
           MICROS_STATE_RUNNING);
    assert(!micros_runtime_stop(runtime, second));
    assert(!micros_runtime_unload(runtime, second));
    baseline(runtime);
    assert(!micros_runtime_destroy(runtime));
    puts("PASS concurrent independent services; peer continues after the other image is reclaimed");
}
static void test_cleanup(const char *directory)
{
    const char *cases[] = {"FAIL_INIT",      "FAIL_START", "FAIL_STEP",  "FAIL_STOP",
                           "CALLBACK_ERROR", "SLOW_INIT",  "SLOW_START", "SLOW_CALLBACK"};
    for (size_t scenario = 0; scenario < sizeof(cases) / sizeof(cases[0]); ++scenario) {
        micros_runtime_config_t config = micros_runtime_default_config();
        config.work_timeout_us = TEST_WORK_US;
        micros_runtime_t *runtime = micros_runtime_create(&config);
        micros_instance_t instance;
        assert(
            !micros_runtime_load(runtime, fixture_path(directory, cases[scenario]), 8, &instance));
        assert(!micros_runtime_start(runtime, instance));
        unsigned writes = scenario == 5 ? 1 : scenario == 6 ? 2 : 3;
        micros_service_status_t status = wait_progress(runtime, instance, writes, 0);
        micros_result_t expected = scenario < 5 ? MICROS_ERROR_SERVICE : MICROS_OK;
        assert(micros_runtime_stop(runtime, instance) == expected);
        assert(!micros_runtime_status(runtime, instance, &status));
        assert(status.state == (expected ? MICROS_STATE_FAILED : MICROS_STATE_STOPPED));
        assert(status.owned_handles == 0 && !status.reboot_required);
        if (scenario == 5 || scenario == 6)
            assert(status.completed_steps == 0 && status.completed_callbacks == 0);
        if (scenario == 7)
            assert(status.completed_callbacks == 1);
        assert(!micros_runtime_unload(runtime, instance));
        baseline(runtime);
        assert(!micros_runtime_destroy(runtime));
    }
    puts("PASS failed init/start/step/stop/callback cleanup, pending stop during init/start, "
         "active callback drain");
}
static void test_hang(const char *directory, const char *scenario)
{
    micros_runtime_config_t config = micros_runtime_default_config();
    config.lifecycle_timeout_us = FAULT_BUDGET_US;
    config.work_timeout_us = FAULT_BUDGET_US;
    micros_runtime_t *runtime = micros_runtime_create(&config);
    micros_instance_t instance;
    assert(!micros_runtime_load(runtime, fixture_path(directory, scenario), 8, &instance));
    assert(!micros_runtime_start(runtime, instance));
    wait_progress(runtime, instance,
                  !strcmp(scenario, "HANG_INIT")    ? 1
                  : !strcmp(scenario, "HANG_START") ? 2
                                                    : 3,
                  0);
    if (!strcmp(scenario, "HANG_INIT")) {
        /* No public status/usage/stop calls here: only the independent supervisor
         * can set recovery while the management controller remains idle. */
        uint64_t deadline = micros_platform_now_us() + TEST_WAIT_US;
        int detected = 0;
        while (!detected && micros_platform_now_us() < deadline) {
            micros_platform_lock(runtime->sync);
            detected = runtime->usage.reboot_required;
            micros_platform_unlock(runtime->sync);
            pause_poll(runtime);
        }
        assert(detected);
    }
    assert(micros_runtime_stop(runtime, instance) == MICROS_ERROR_REBOOT_REQUIRED);
    micros_runtime_usage_t retained = micros_runtime_usage(runtime);
    assert(retained.reboot_required && retained.loaded_services == 1 && retained.live_tasks == 1 &&
           retained.live_handles > 0);
    assert(micros_runtime_unload(runtime, instance) == MICROS_ERROR_REBOOT_REQUIRED);
    assert(micros_runtime_destroy(runtime) == MICROS_ERROR_REBOOT_REQUIRED);
    assert(micros_runtime_start(runtime, instance) == MICROS_ERROR_REBOOT_REQUIRED);
    assert(micros_runtime_load(runtime, fixture_path(directory, "NORMAL"), 0, &instance) ==
           MICROS_ERROR_REBOOT_REQUIRED);
    printf("PASS %s timeout retains image/arena/stack/handles/task and requires process recovery\n",
           scenario);
    fflush(NULL);
    _Exit(0); /* Test parent owns process recovery; never free under the hung thread. */
}
static void test_console_ports(const char *directory)
{
    micros_runtime_config_t config=micros_runtime_default_config();
    micros_runtime_t *r=micros_runtime_create(&config); micros_instance_t instance;
    assert(!micros_runtime_channel_create(r,1,MICROS_CHANNEL_STREAM,2,32));
    assert(!micros_runtime_load(r,fixture_path(directory,"NORMAL"),8,&instance));
    assert(!micros_runtime_start(r,instance));
    micros_service_status_t live=wait_progress(r,instance,2,1);
    assert(live.state==MICROS_STATE_RUNNING);
    micros_context_t *context=&find_service(r,instance)->context;
    micros_handle_t pub,sub;
    assert(!api_ipc_open(context,1,MICROS_IPC_PUBLISH,&pub));
    assert(!api_ipc_open(context,1,MICROS_IPC_SUBSCRIBE,&sub));
    uint8_t payload[33]={8,42,21,0,255,68,187},output[32];uint32_t bytes=0;micros_message_info_t info={0};
    assert(micros_runtime_console_write(r,instance,2,payload,7)==MICROS_ERROR_UNSUPPORTED);
    assert(micros_runtime_console_write(r,instance,1,payload,33)==MICROS_ERROR_CAPACITY);
    assert(!micros_runtime_console_write(r,instance,1,payload,7));
    assert(!micros_runtime_console_read(r,instance,1,output,32,&bytes,&info));
    assert(bytes==7 && !memcmp(payload,output,7));
    assert(micros_runtime_console_read(r,instance,1,output,32,&bytes,&info)==MICROS_ERROR_EMPTY);
    assert(!micros_runtime_stop(r,instance));
    assert(micros_runtime_console_write(r,instance,1,payload,7)==MICROS_ERROR_STATE);
    assert(!micros_runtime_unload(r,instance));
    assert(micros_runtime_console_write(r,instance,1,payload,7)==MICROS_ERROR_STATE);
    assert(!micros_runtime_channel_destroy(r,1));assert(!micros_runtime_destroy(r));
    puts("PASS console reuses owned ports, bounds payloads, and rejects stopped/stale instances");
}
static void test_coordination(const char *directory)
{
    for (unsigned kind=1;kind<=3;++kind) {
        micros_runtime_t *r[2];micros_instance_t id[2];micros_context_t *ctx[2];micros_handle_t h[2];
        for(unsigned i=0;i<2;++i) {
            micros_runtime_config_t config=micros_runtime_default_config();
            r[i]=micros_runtime_create(&config);
            assert(!micros_runtime_channel_create(r[i],1,MICROS_CHANNEL_LATEST,1,32));
            assert(!micros_runtime_load(r[i],fixture_path(directory,"NORMAL"),8,&id[i]));
            assert(!micros_runtime_start(r[i],id[i]));wait_progress(r[i],id[i],2,1);
            ctx[i]=&find_service(r[i],id[i])->context;
            assert(!api_coord_open(ctx[i],1,i ? MICROS_IPC_SUBSCRIBE : MICROS_IPC_PUBLISH,kind,&h[i]));
            assert(!micros_runtime_coord_bind(r[i],1,kind,i+1,77));
        }
        uint8_t data[32]={8,42},wire[112],reply[112];uint32_t bytes=2,size=0,reply_size=0;
        micros_coord_info_t info={0},ticket={0};
        unsigned write=kind==1 ? MICROS_COORD_SET : kind==2 ? MICROS_COORD_REQUEST : MICROS_COORD_EMIT;
        unsigned read=kind==1 ? MICROS_COORD_READ : kind==2 ? MICROS_COORD_NEXT : MICROS_COORD_RECEIVE;
        assert(!api_coord(ctx[0],h[0],write,data,sizeof(data),&bytes,&info));
        assert(info.revision==1 && info.generation==77);
        assert(!micros_runtime_coord_exchange(r[0],1,NULL,0,wire,&size));
        uint8_t wrong[112];memcpy(wrong,wire,size);wrong[8]^=1;
        assert(micros_runtime_coord_exchange(r[1],1,wrong,size,reply,&reply_size));
        assert(!micros_runtime_coord_exchange(r[1],1,wire,size,reply,&reply_size));
        assert(!api_coord(ctx[1],h[1],read,data,sizeof(data),&bytes,&ticket));
        assert(bytes==2 && data[1]==42 && ticket.revision==1);
        assert(api_ipc_publish(ctx[0],h[0],data,2)==MICROS_ERROR_UNSUPPORTED);
        assert(!micros_runtime_coord_exchange(r[1],1,wire,size,reply,&reply_size));
        assert(api_coord(ctx[1],h[1],read,data,sizeof(data),&bytes,&info)==MICROS_ERROR_EMPTY);
        if(kind==MICROS_COORD_ACTION) {
            assert(api_coord(ctx[0],h[0],write,data,sizeof(data),&bytes,&info)==MICROS_ERROR_STATE);
            ticket.status=MICROS_COORD_COMPLETED;
            assert(!api_coord(ctx[1],h[1],MICROS_COORD_COMPLETE,data,sizeof(data),&bytes,&ticket));
            assert(api_coord(ctx[1],h[1],MICROS_COORD_COMPLETE,data,sizeof(data),&bytes,&ticket)==MICROS_ERROR_STATE);
            assert(!micros_runtime_coord_exchange(r[1],1,wire,size,reply,&reply_size));
            assert(!micros_runtime_coord_exchange(r[0],1,reply,reply_size,wire,&size));
            assert(!api_coord(ctx[0],h[0],MICROS_COORD_RESULT,data,sizeof(data),&bytes,&info));
            assert(info.status==MICROS_COORD_COMPLETED && info.revision==1);
            assert(!api_coord(ctx[0],h[0],write,data,sizeof(data),&bytes,&info));
            assert(info.revision==2);
            assert(api_coord(ctx[0],h[0],MICROS_COORD_RESULT,data,sizeof(data),&bytes,&info)==MICROS_ERROR_EMPTY);
            assert(!micros_runtime_coord_exchange(r[0],1,NULL,0,wire,&size));
            assert(!micros_runtime_coord_exchange(r[1],1,wire,size,reply,&reply_size));
            assert(!api_coord(ctx[1],h[1],read,data,sizeof(data),&bytes,&ticket));
            assert(!api_ipc_close(ctx[1],h[1]));
            assert(r[1]->coordination[0]->result.status==MICROS_COORD_INDETERMINATE);
        } else {
            data[1]=99;bytes=2;
            assert(!api_coord(ctx[0],h[0],write,data,sizeof(data),&bytes,&info));
            assert(info.revision==2);
        }
        for(unsigned i=0;i<2;++i) {
            assert(!micros_runtime_stop(r[i],id[i]));assert(!micros_runtime_unload(r[i],id[i]));
            assert(!micros_runtime_channel_destroy(r[i],1));assert(!micros_runtime_destroy(r[i]));
        }
    }
    puts("PASS production coordination state/action/event, duplicate/loss recovery, fencing and interrupted actions");
}
static void test_stale_coordination_cleanup(const char *directory)
{
    for (unsigned unload=0; unload<2; ++unload) {
        micros_runtime_config_t config=micros_runtime_default_config();
        micros_runtime_t *r=micros_runtime_create(&config);
        micros_instance_t old_owner, new_owner;
        assert(!micros_runtime_load(r,fixture_path(directory,"NORMAL"),8,&old_owner));
        assert(!micros_runtime_load(r,fixture_path(directory,"NORMAL_PEER"),8,&new_owner));
        assert(!micros_runtime_start(r,old_owner));wait_progress(r,old_owner,2,1);
        assert(!micros_runtime_start(r,new_owner));wait_progress(r,new_owner,2,1);
        micros_context_t *old_ctx=&find_service(r,old_owner)->context;
        micros_context_t *new_ctx=&find_service(r,new_owner)->context;
        micros_handle_t stale, publisher, subscriber;
        assert(!micros_runtime_channel_create(r,1,MICROS_CHANNEL_LATEST,1,32));
        assert(!api_coord_open(old_ctx,1,MICROS_IPC_SUBSCRIBE,MICROS_COORD_ACTION,&stale));
        assert(!micros_runtime_channel_destroy(r,1));
        assert(!micros_runtime_channel_create(r,1,MICROS_CHANNEL_LATEST,1,32));
        assert(!api_coord_open(new_ctx,1,MICROS_IPC_PUBLISH,MICROS_COORD_ACTION,&publisher));
        assert(!api_coord_open(new_ctx,1,MICROS_IPC_SUBSCRIBE,MICROS_COORD_ACTION,&subscriber));
        uint8_t data[32]={8,42};uint32_t bytes=2;
        micros_coord_info_t request={0},ticket={0},result={0};
        assert(!api_coord(new_ctx,publisher,MICROS_COORD_REQUEST,data,sizeof(data),&bytes,&request));
        assert(!api_coord(new_ctx,subscriber,MICROS_COORD_NEXT,data,sizeof(data),&bytes,&ticket));
        if (unload) {
            assert(!micros_runtime_stop(r,old_owner));
            assert(!micros_runtime_unload(r,old_owner));
        }
        else assert(!api_ipc_close(old_ctx,stale));
        assert(!api_coord(new_ctx,publisher,MICROS_COORD_RESULT,data,sizeof(data),&bytes,&result));
        assert(result.status==MICROS_COORD_ACCEPTED);
        ticket.status=MICROS_COORD_COMPLETED;
        assert(!api_coord(new_ctx,subscriber,MICROS_COORD_COMPLETE,data,sizeof(data),&bytes,&ticket));
        assert(!api_coord(new_ctx,publisher,MICROS_COORD_RESULT,data,sizeof(data),&bytes,&result));
        assert(result.status==MICROS_COORD_COMPLETED);
        if (!unload) {
            assert(!micros_runtime_stop(r,old_owner));
            assert(!micros_runtime_unload(r,old_owner));
        }
        assert(!micros_runtime_stop(r,new_owner));
        assert(!micros_runtime_unload(r,new_owner));
        assert(!micros_runtime_channel_destroy(r,1));
        assert(!micros_runtime_destroy(r));
    }
    puts("PASS stale coordination close and owner unload preserve recreated channel actions");
}
int main(int argc, char **argv)
{
    assert(argc == 2 || argc == 3);
    if (argc == 3)
        test_hang(argv[1], argv[2]);
    test_configuration_storage(argv[1]);
    test_individual_restart(argv[1]);
    test_coordination(argv[1]);
    test_stale_coordination_cleanup(argv[1]);
    test_console_ports(argv[1]);
    test_manifest_policy(argv[1]);
    test_admission(argv[1]);
    test_ownership(argv[1]);
    test_cycles(argv[1]);
    test_concurrent_services(argv[1]);
    test_cleanup(argv[1]);
    return 0;
}
