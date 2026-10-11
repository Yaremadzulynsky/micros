#include <micros/platform.h>
#include <micros/capabilities.h>
#include <micros/deployment.h>
#include "image.h"
#include <micros/transport.h>
#include <micros/update.h>
#include <micros/network.h>
#include "runtime.h"
#include <micros/status.h>
#include <micros/application.h>
#include <micros/storage.h>
#include <errno.h>
#include <inttypes.h>
#include <micros/platform.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "support/output.h"

/* Serial remains the physical development interface; the command and binary
 * transfer bounds are separate from service-visible payload/arena budgets. */
#define COMMAND_BYTES MICROS_CONTROLLER_COMMAND_BYTES /* WIFI SET needs 9 + 64 + 1 + 128 hex characters and a terminator. */
#define FILE_PATH_BYTES MICROS_CONTROLLER_IMAGE_PATH_BYTES
#define TRANSFER_TIMEOUT_US UINT64_C(10000000)
/* Five seconds allows fifty sensor callbacks and thousands of cooperative steps
 * before a trial is called healthy. It establishes liveness, not application correctness. */
#define HEALTH_WINDOW_US UINT64_C(5000000)
static uint64_t health_deadline_us;
static int physical_recovery;
static uint64_t service_boot;
static micros_runtime_t *runtime;
static micros_instance_t instances[MICROS_BOARD_IMAGE_SLOTS];
static unsigned instance_count;
static int running_bank = -1;
static unsigned baseline_heap;
static unsigned failed_bank=MICROS_ACTIVATION_NONE, failed_attempts;
static const char *failed_reason="none";
/* Renewed after each admitted mutation: long enough for bounded TLS requests
 * and a local Docker round-trip, finite if the updater disappears after STOP. */
#define DEPLOYMENT_SESSION_US UINT64_C(60000000)
static char deployment_session[33];
static uint64_t deployment_deadline;
static micros_activation_record_t deployment_previous;
static int deployment_stopped;

static struct { unsigned bank,slot;size_t total,written;int active;micros_device_graph_t *graph; } transfer;
static void transfer_abort(void) { free(transfer.graph);memset(&transfer,0,sizeof(transfer)); }
static int prepared_bank=-1;
static int prepare_store(unsigned bank) {
 if(prepared_bank==(int)bank)return 1;
 micros_activation_record_t record=micros_storage_selection();
 if(bank>=2 || bank==record.good || record.pending)return 0;
 if(record.previous==bank) {
  record.previous=MICROS_ACTIVATION_NONE;memset(record.previous_hash,0,sizeof(record.previous_hash));
  if(!micros_storage_select(record))return 0;
 }
 if(!micros_storage_prepare(bank))return 0;
 prepared_bank=(int)bank;return 1;
}
static void image_path(char *path, unsigned bank, unsigned slot)
{
    micros_storage_image_path(bank, slot, path, FILE_PATH_BYTES);
}
static int read_exact(void *output, size_t bytes)
{
    size_t received = 0;
    uint64_t deadline = micros_platform_now_us() + TRANSFER_TIMEOUT_US;
    while (received < bytes && micros_platform_now_us() < deadline) {
        int chunk = micros_controller_read((uint8_t *)output + received, bytes - received, 100);
        if (chunk > 0)
            received += chunk;
    }
    return received == bytes;
}
_Static_assert(MICROS_GRAPH_CONFIG_BYTES == MICROS_CONFIG_MAX_BYTES,
               "Stored and runtime configuration limits must match");
static int valid_graph(const micros_device_graph_t *graph)
{
    if (graph->magic != MICROS_GRAPH_MAGIC || graph->version != MICROS_GRAPH_VERSION ||
        graph->bank >= MICROS_GRAPH_BANKS || !graph->service_count ||
        graph->service_count > MICROS_BOARD_IMAGE_SLOTS ||
        graph->channel_count > MICROS_GRAPH_CHANNELS || !micros_board_validate_gpio(graph) ||
        graph->checksum !=
            micros_crc32((const void *)graph, offsetof(micros_device_graph_t, checksum)))
        return 0;
    uint32_t channel_mask = 0, publishers = 0, subscribers = 0, slots = 0, gpio_claims = 0, imported_latest = 0;
    size_t arena = 0, stacks = 0;
    for (unsigned index = 0; index < MICROS_GRAPH_CHANNELS; ++index) {
        const micros_graph_channel_t *channel = &graph->channels[index];
        if (index >= graph->channel_count) {
            if (channel->key || channel->policy || channel->depth || channel->payload_bytes)
                return 0;
            continue;
        }
        if (!channel->key || channel->key > 32 || !channel->depth || channel->depth > 8 ||
            !channel->payload_bytes || channel->payload_bytes > 256 ||
            (channel->policy != MICROS_CHANNEL_STREAM &&
             channel->policy != MICROS_CHANNEL_LATEST) ||
            (channel->policy == MICROS_CHANNEL_LATEST && channel->depth != 1))
            return 0;
        uint32_t bit = UINT32_C(1) << (channel->key - 1);
        if (channel_mask & bit)
            return 0;
        channel_mask |= bit;
    }
    for (unsigned index = 0; index < MICROS_BOARD_IMAGE_SLOTS; ++index) {
        const micros_graph_service_t *service = &graph->services[index];
        const micros_graph_config_t *configuration = &graph->configurations[index];
        if (configuration->bytes > MICROS_GRAPH_CONFIG_BYTES ||
            (index >= graph->service_count && configuration->bytes))
            return 0;
        for (unsigned byte = configuration->bytes; byte < MICROS_GRAPH_CONFIG_BYTES; ++byte)
            if (configuration->data[byte])
                return 0;
        if (index >= graph->service_count) {
            micros_graph_service_t zero = {0};
            if (memcmp(service, &zero, sizeof(zero)))
                return 0;
            continue;
        }
        if (service->slot >= MICROS_BOARD_IMAGE_SLOTS || slots & (1u << service->slot) ||
            service->handles > MICROS_RUNTIME_HANDLES_PER_SERVICE ||
            service->timers > service->handles ||
            service->gpio_mask >= (1u << graph->gpio_count) ||
            (service->gpio_mask & gpio_claims) ||
            (service->publish_mask | service->subscribe_mask) & ~channel_mask ||
            service->arena_bytes > 4096 || !service->arena_alignment ||
            service->arena_alignment > 16 ||
            (service->arena_alignment & (service->arena_alignment - 1)) ||
            !service->stack_bytes || service->stack_bytes > 16384)
            return 0;
        unsigned minimum_handles = service->timers + __builtin_popcount(service->gpio_mask) +
                                   __builtin_popcount(service->publish_mask) +
                                   __builtin_popcount(service->subscribe_mask);
        if (minimum_handles > service->handles)
            return 0;
        slots |= 1u << service->slot;
        gpio_claims |= service->gpio_mask;
        publishers |= service->publish_mask;
        subscribers |= service->subscribe_mask;
        arena += service->arena_bytes;
        stacks += service->stack_bytes;
    }
    /* Generated coordination ports can subscribe to an imported latest channel.
     * Authenticated package admission checks its explicit kind and schema. */
    for (unsigned i=0;i<graph->channel_count;++i)
        if (graph->channels[i].policy==MICROS_CHANNEL_LATEST)
            imported_latest |= 1u << (graph->channels[i].key-1);
    return !(subscribers & ~publishers & ~imported_latest) && arena <= MICROS_CONTROLLER_ARENA_BYTES && stacks <= MICROS_CONTROLLER_STACK_BYTES;
}
static int load_graph(unsigned bank, micros_device_graph_t *graph)
{
    return micros_storage_read_graph(bank, graph) && graph->bank == bank && valid_graph(graph);
}
#include <micros/ipc_console.h>
#include "coordination_console.h"

static void recover_if_needed(void)
{
    if (runtime && micros_runtime_usage(runtime).reboot_required) {
        controller_event("RECOVERY reboot required; native resources retained\n");
        fflush(stdout);
        micros_controller_reset();
    }
}
static int stop_graph(void)
{
    if (!runtime)
        return 1;
    if (micros_application_close(&runtime, instances, instance_count)) {
        recover_if_needed();
        return 0;
    }
    instance_count = 0;
    health_deadline_us = 0;
    running_bank = -1;
    return 1;
}
static int boot_graph(unsigned bank)
{
    micros_device_graph_t *graph=malloc(sizeof(*graph));
    if(!graph)return 0;
    if (!load_graph(bank, graph) || !stop_graph())
        { free(graph);return 0; }
    if (!micros_board_apply_gpio(graph)) { free(graph);return 0; }
    micros_runtime_config_t config = micros_runtime_default_config();
    config.image_bytes =
        MICROS_BOARD_IMAGE_SLOTS * (MICROS_BOARD_CODE_BYTES + MICROS_BOARD_DATA_BYTES);
    config.arena_bytes = MICROS_CONTROLLER_ARENA_BYTES;
    config.stack_bytes = MICROS_CONTROLLER_STACK_BYTES;
    config.channel_bytes = MICROS_CONTROLLER_CHANNEL_BYTES;
    config.supervisor_stack_bytes = MICROS_CONTROLLER_SUPERVISOR_STACK;
    config.platform_stack_bytes = 0;
    for (unsigned i=0;i<graph->service_count;++i)
        config.platform_stack_bytes += micros_platform_stack_bytes(graph->services[i].stack_bytes);
    runtime = micros_runtime_create(&config);
    if (!runtime)
        { free(graph);return 0; }
    for (unsigned index = 0; index < graph->channel_count; ++index) {
        micros_graph_channel_t *channel = &graph->channels[index];
        if (micros_runtime_channel_create(runtime, channel->key, channel->policy, channel->depth,
                                          channel->payload_bytes))
            goto fail;
    }
    for (unsigned index = 0; index < graph->service_count; ++index) {
        micros_graph_service_t *service = &graph->services[index];
        char path[FILE_PATH_BYTES];
        image_path(path, bank, service->slot);
        micros_application_service_t input = {
            .image_path = path, .handles = service->handles,
            .policy = {service->timers, service->gpio_mask, service->publish_mask, service->subscribe_mask},
            .configuration = graph->configurations[index].data,
            .configuration_bytes = graph->configurations[index].bytes,
            .verify_memory = 1, .arena_bytes = service->arena_bytes,
            .arena_alignment = service->arena_alignment, .stack_bytes = service->stack_bytes,
        };
        micros_result_t result = micros_application_admit(runtime, &input, &instances[index]);
        if (instances[index]) ++instance_count;
        if (result) goto fail;
    }
    uint32_t publish_masks[MICROS_RUNTIME_SERVICE_CAPACITY] = {0};
    for (unsigned index = 0; index < instance_count; ++index)
        publish_masks[index] = graph->services[index].publish_mask;
    if (micros_application_start(runtime, instances, publish_masks, instance_count,
                                  config.lifecycle_timeout_us)) goto fail;
    running_bank = bank;
    free(graph);return 1;
fail:
    recover_if_needed();
    stop_graph();
    free(graph);return 0;
}
/** @brief Validate complete bank identity before any independently loaded hook runs. */
static int bank_matches(unsigned bank, const uint8_t *expected)
{
    uint8_t observed[MICROS_ACTIVATION_HASH_BYTES];
    return micros_deployment_hash(bank, observed) &&
           !memcmp(observed, expected, sizeof(observed));
}
static void clear_trial(micros_activation_record_t *record)
{
    record->pending = 0;
    record->candidate = MICROS_ACTIVATION_NONE;
    record->attempts = 0;
    memset(record->candidate_hash, 0, sizeof(record->candidate_hash));
}
/** @brief Base-owned fallback is independent of candidate service execution. */
static void activation_boot(void)
{
    micros_activation_record_t record = micros_storage_selection();
    if (record.pending && record.attempts >= MICROS_ACTIVATION_ATTEMPTS) {
        failed_bank=record.candidate;failed_attempts=record.attempts;failed_reason="attempts exhausted";
        clear_trial(&record);
        if (!micros_storage_select(record)) {
            physical_recovery = 1;
            return;
        }
        controller_event("ROLLBACK attempts exhausted\n");
        record = micros_storage_selection();
    }
    uint32_t bank = micros_activation_boot_bank(&record);
    if (bank == MICROS_ACTIVATION_NONE)
        return;
    const uint8_t *hash = record.pending ? record.candidate_hash : record.good_hash;
    if (!micros_base_application_allowed(hash))
        return; /* Retained packages belong to a different base; await explicit deployment. */
    if (!bank_matches(bank, hash)) {
        controller_event("REJECT selected bank integrity\n");
        if (record.pending) {
            failed_bank=record.candidate;failed_attempts=record.attempts;failed_reason="image integrity";
            clear_trial(&record);
            if (micros_storage_select(record)) {
                activation_boot();
                return;
            }
        }
        physical_recovery = 1;
        return;
    }
    if (record.pending) {
        ++record.attempts; /* Persist the attempt before entering any candidate code. */
        if (!micros_storage_select(record)) {
            physical_recovery = 1;
            return;
        }
        micros_storage_fault_boundary(10);
    }
    if (!boot_graph(bank)) {
        controller_event("AUTOBOOT REJECT\n");
        fflush(stdout);
        if (record.pending)
            micros_controller_reset();
        physical_recovery = 1;
        return;
    }
    health_deadline_us = record.pending ? micros_platform_now_us() + HEALTH_WINDOW_US : 0;
    controller_event("AUTOBOOT OK bank=%u trial=%u\n", (unsigned)bank, (unsigned)record.pending);
    micros_storage_fault_boundary(11);
}
#include "support/selective.inc"

static void poll_health(void)
{
    if (!health_deadline_us || !runtime)
        return;
    for (unsigned index = 0; index < instance_count; ++index) {
        micros_service_status_t status = {0};
        micros_runtime_status(runtime, instances[index], &status);
        if (selective.active && (selective.changed & (1u << index)) &&
            (status.state == MICROS_STATE_INITIALIZING || status.state == MICROS_STATE_STARTING) &&
            micros_platform_now_us() < health_deadline_us) continue;
        if (status.state != MICROS_STATE_RUNNING || status.result) {
            if (selective.active) { selective_restore(); return; }
            controller_event("HEALTH FAILED\n");
            fflush(stdout);
            micros_controller_reset();
        }
        if (micros_platform_now_us() >= health_deadline_us && !status.completed_steps) {
            if (selective.active) { selective_restore(); return; }
            controller_event("HEALTH no progress\n");
            fflush(stdout);
            micros_controller_reset();
        }
    }
    if (micros_platform_now_us() < health_deadline_us)
        return;
    micros_activation_record_t record = micros_storage_selection();
    /* Confirmation is a new atomic selection; the previous good bank remains intact. */
    record.previous = record.good;
    memcpy(record.previous_hash, record.good_hash, sizeof(record.good_hash));
    record.good = record.candidate;
    memcpy(record.good_hash, record.candidate_hash, sizeof(record.good_hash));
    clear_trial(&record);
    if (!live_select(record, 0)) {
        controller_event("HEALTH storage failure\n");
        fflush(stdout);
        micros_controller_reset();
    }
    health_deadline_us = 0;
    selective.active = 0;
    controller_event("HEALTH COMMITTED bank=%u\n", (unsigned)record.good);
    fflush(stdout);
    micros_storage_fault_boundary(12);
}
static __attribute__((noinline)) int prepare_activation(unsigned bank)
{
    micros_device_graph_t *graph=malloc(sizeof(*graph));
    if (!graph) return 0;
    int result=0;
    if (!load_graph(bank, graph)) goto done;
    int transition=selective_begin(bank, graph);
    if (transition) { result=transition>0?2:0;goto done; }
    if (!stop_graph()) goto done;
    for (unsigned index=0;index<graph->service_count;++index) {
        char path[FILE_PATH_BYTES];
        image_path(path,bank,graph->services[index].slot);
        if (micros_board_validate_image(path,graph->services[index].slot)) goto done;
    }
    result=1;
done:
    free(graph);
    return result;
}

static int activate_bank(unsigned bank)
{
    prepared_bank=-1;
    micros_activation_record_t record = micros_storage_selection();
    if (bank >= MICROS_GRAPH_BANKS || physical_recovery || record.pending || micros_base_pending())
        return 0;
    if (bank == record.good)
        return bank_matches(bank, record.good_hash) && micros_base_bind_application(bank, record.good_hash) && boot_graph(bank);
    int prepared=prepare_activation(bank);
    if(prepared!=1)return prepared==2;
    if (!micros_deployment_hash(bank, record.candidate_hash))
        return 0;
    record.candidate = bank;
    record.pending = 1;
    record.attempts = 0;
    /* A new trial may reuse the older retained bank; only current good is protected. */
    record.previous = MICROS_ACTIVATION_NONE;
    memset(record.previous_hash, 0, sizeof(record.previous_hash));
    if (!micros_base_bind_application(bank, record.candidate_hash) || !micros_storage_select(record))
        return 0;
    activation_boot();
    return runtime != NULL;
}
static void report_status(void)
{
    micros_activation_record_t record = micros_storage_selection();
    printf("ACTIVATION sequence=%u good=%u previous=%u candidate=%u attempts=%u pending=%u "
           "recovery=%u\n",
           (unsigned)record.sequence, (unsigned)record.good, (unsigned)record.previous,
           (unsigned)record.candidate, (unsigned)record.attempts, (unsigned)record.pending,
           (unsigned)physical_recovery);
    unsigned heap = micros_controller_heap_free();
    printf("STATUS bank=%d services=%u heap=%u baseline_heap=%u recovery_button=%d\n", running_bank,
           instance_count, heap, baseline_heap,
           micros_board_recovery_pin()>=0 ? micros_controller_gpio_level(micros_board_recovery_pin()) : -1
    );
    if (runtime) {
        micros_runtime_usage_t usage = micros_runtime_usage(runtime);
        printf("USAGE image=%u arena=%u stack=%u metadata=%u handles=%u channels=%u "
               "channel_bytes=%u callbacks=%u\n",
               (unsigned)usage.image_bytes, (unsigned)usage.arena_bytes,
               (unsigned)usage.platform_stack_bytes, (unsigned)usage.kernel_metadata_bytes,
               (unsigned)usage.live_handles, (unsigned)usage.channels,
               (unsigned)usage.channel_bytes, (unsigned)usage.active_callbacks);
        for (unsigned index = 0; index < instance_count; ++index) {
            micros_service_status_t status = {0};
            micros_runtime_status(runtime, instances[index], &status);
            printf("SERVICE index=%u state=%s result=%d steps=%" PRIu64 " callbacks=%" PRIu64
                   " stack_free=%u\n",
                   index, micros_runtime_state_name(status.state), (int)status.result,
                   status.completed_steps, status.completed_callbacks,
                   (unsigned)status.stack_free_bytes);
        }
    }
    printf("END STATUS\n");
}
static uint64_t management_reboot_us;
static uint64_t management_bootloader_us;
/** Privileged management service delegates all mutations to the same base controller. */
static void finish_deployment_session(void)
{
    transfer_abort();
    prepared_bank=-1;
    micros_base_abort();
    micros_activation_record_t selected = micros_storage_selection();
    if (deployment_stopped && !runtime && !physical_recovery && !selected.pending &&
        selected.good == deployment_previous.good && selected.good < MICROS_GRAPH_BANKS &&
        !memcmp(selected.good_hash, deployment_previous.good_hash, sizeof(selected.good_hash))) {
        controller_event("MANAGEMENT restoring abandoned deployment\n");
        (void)activate_bank(selected.good);
    }
    deployment_session[0] = 0;
    deployment_deadline = 0;
    deployment_stopped = 0;
}

#include "protocol/restart.inc"

static __attribute__((noinline)) void management_status(micros_management_request_t *request)
{

        /* Target supplies the exact running base identity. */
        char base_hash[65]; /* SHA-256 hex plus terminator. */
        const volatile uint8_t *elf_hash = micros_controller_base_hash();
        for (size_t index = 0; index < 32; ++index)
            snprintf(base_hash + 2 * index, 3, "%02x", elf_hash[index]);
        uint8_t device_mac[6];
        micros_controller_identity(device_mac);
        micros_activation_record_t record = micros_storage_selection();
        char good_hash[2 * MICROS_ACTIVATION_HASH_BYTES + 1];
        for (size_t index = 0; index < MICROS_ACTIVATION_HASH_BYTES; ++index)
            snprintf(good_hash + 2 * index, 3, "%02x", record.good_hash[index]);
        size_t used = (size_t)snprintf(
            request->response, request->response_capacity,
            "{\"identity\":{\"device_id\":\"%02x%02x%02x%02x%02x%02x\","
            "\"base_sha256\":\"%s\",\"abi_major\":%u,\"abi_revision\":%u,"
            "\"graph_format\":%u,\"slots\":%u,\"code_bytes\":%u,\"data_bytes\":%u},"
            "\"platform\":\"" MICROS_PLATFORM_NAME "\",\"target\":%u,\"ipc_stream\":1,\"service_restart\":1,\"selective_deploy\":%u,\"service_boot\":\"%" PRIu64 "\",\"uptime_us\":%" PRIu64 ",\"reset_reason\":%u,\"physical_recovery\":%s,"
            "\"deployment_session\":\"%s\",\"last_failure\":{\"bank\":%u,\"attempts\":%u,\"reason\":\"%s\"},"
            "\"activation\":{\"sequence\":%u,\"good\":%u,\"previous\":%u,\"candidate\":%u,"
            "\"attempts\":%u,\"pending\":%u,\"good_sha256\":\"%s\"},\"heap\":%u,\"services\":[",
            device_mac[0], device_mac[1], device_mac[2], device_mac[3], device_mac[4], device_mac[5],
            base_hash, (unsigned)MICROS_ABI_MAJOR, (unsigned)MICROS_ABI_REVISION,
            MICROS_GRAPH_VERSION, MICROS_BOARD_IMAGE_SLOTS, MICROS_BOARD_CODE_BYTES,
            MICROS_BOARD_DATA_BYTES, MICROS_TARGET_ID, MICROS_CAP_SELECTIVE_UPDATE, service_boot, micros_platform_now_us(), (unsigned)micros_controller_reset_reason(),
            physical_recovery ? "true" : "false",
            deployment_session,failed_bank,failed_attempts,failed_reason,
            (unsigned)record.sequence, (unsigned)record.good, (unsigned)record.previous,
            (unsigned)record.candidate, (unsigned)record.attempts, (unsigned)record.pending,
            good_hash, (unsigned)micros_controller_heap_free());
        for (unsigned index = 0; index < instance_count && used < request->response_capacity;
             ++index) {
            micros_service_status_t status = {0};
            micros_runtime_status(runtime, instances[index], &status);
            used += (size_t)snprintf(request->response + used, request->response_capacity - used,
                                     "%s{\"index\":%u,\"instance\":\"%" PRIu64 "\",\"state\":\"%s\",\"result\":%d,\"steps\":%" PRIu64
                                     ",\"callbacks\":%" PRIu64 ",\"stack_free_bytes\":%u,\"arena_reserved\":%u,\"arena_pool\":\"%s\",\"stack_reserved\":%u,\"handles_open\":%u,\"handles_limit\":%u,\"timers_open\":%u,\"timers_limit\":%u,\"gpio_granted\":%u,\"gpio_open\":%u,\"publish_mask\":%u,\"subscribe_mask\":%u,\"hook_max_us\":%" PRIu64 ",\"callback_max_us\":%" PRIu64 ",\"timer_late_max_us\":%" PRIu64 "}",
                                     index ? "," : "", index, instances[index], micros_runtime_state_name(status.state),
                                     (int)status.result, status.completed_steps,
                                     status.completed_callbacks, (unsigned)status.stack_free_bytes,
                                     (unsigned)status.arena_bytes,status.arena_placement ? "PSRAM" : "RAM",(unsigned)status.stack_bytes,(unsigned)status.owned_handles,(unsigned)status.handle_limit,
                                     (unsigned)status.timers_open,(unsigned)status.timer_limit,(unsigned)status.gpio_granted,(unsigned)status.gpio_open,
                                     (unsigned)status.publish_mask,(unsigned)status.subscribe_mask,status.hook_max_us,status.callback_max_us,status.timer_late_max_us);
        }
        if (used < request->response_capacity-1) request->response[used++]=']';
        micros_hardware_snapshot_t hardware;
        micros_platform_telemetry(&hardware);
        used=micros_status_append(request->response,request->response_capacity,used,runtime,
                                  &hardware,micros_wifi_insights);
        if (used + 12 < request->response_capacity) {
            memcpy(request->response + used, ",\"base_ota\":", 12);
            used += 12;
            size_t added = micros_base_status(request->response + used, request->response_capacity - used);
            used = added ? used + added : request->response_capacity;
        } else used = request->response_capacity;
        if (used < request->response_capacity-1) {
            request->response[used++]='}'; request->response[used]=0;
        } else {
            request->result=1;
            snprintf(request->response,request->response_capacity,"{\"error\":\"status_capacity\"}");
        }
        return;
    }

static __attribute__((noinline)) void management_platform_command(micros_management_request_t *request)
{

        if (!request->body_bytes || request->body_bytes >= 256 ||
            memchr(request->body,0,request->body_bytes) || micros_base_busy() || micros_base_pending()) {
            request->result=1; snprintf(request->response,request->response_capacity,"IPC ERROR -1"); return;
        }
        char command[256];
        memcpy(command,request->body,request->body_bytes);command[request->body_bytes]=0;
        if (!strncmp(command, "SERVICE RESTART ", 16)) {
            service_restart_command(request, command);
            return;
        }
        if (!strncmp(command,"IPC DRAIN ",10)) {
            unsigned index=0,key=0,sequence=0; char expected[65]={0}; int end=0;
            micros_activation_record_t selected=micros_storage_selection();
            int valid=sscanf(command,"IPC DRAIN %u %u %u %64s%n",&index,&key,&sequence,expected,&end)==4 &&
                end && !command[end] && strlen(expected)==64 && key>0 && key<=32 && index<instance_count &&
                runtime && !selected.pending && selected.good<2 && selected.sequence==sequence && !physical_recovery;
            for (unsigned i=0; valid && i<32; ++i) {
                int hi=micros_ipc_hex(expected[i*2]),lo=micros_ipc_hex(expected[i*2+1]);
                if(hi<0 || lo<0 || (unsigned)((hi<<4)|lo)!=selected.good_hash[i]) valid=0;
            }
            if (!valid || deployment_session[0])
                snprintf(request->response,request->response_capacity,"{\"events\":[],\"error\":-3}");
            else micros_ipc_batch(runtime,instances[index],key,request->response,request->response_capacity);
            request->result=0; return;
        }
        char *reply=request->response+16;
        size_t reply_capacity=request->response_capacity-18;
        if (!strncmp(command,"COORD ",6)) {
            micros_activation_record_t selected=micros_storage_selection();
            if (!runtime || selected.pending || physical_recovery || deployment_session[0])
                snprintf(reply,reply_capacity,"COORD ERROR -3");
            else micros_coord_console(runtime,command,reply,reply_capacity);
        } else micros_ipc_command(runtime, instances, instance_count, command,reply,reply_capacity);
        size_t reply_bytes=strlen(reply);
        memmove(request->response+10,reply,reply_bytes);
        memcpy(request->response,"{\"reply\":\"",10);
        memcpy(request->response+10+reply_bytes,"\"}",3);
        request->result=0; return;
    }

static __attribute__((noinline)) void management_logs(micros_management_request_t *request) {
        uint8_t data[256];size_t bytes=micros_transport_read_log(data,sizeof(data));
        size_t used=(size_t)snprintf(request->response,request->response_capacity,"{\"hex\":\"");
        for(size_t i=0;i<bytes;++i)used+=(size_t)snprintf(request->response+used,request->response_capacity-used,"%02x",data[i]);
        snprintf(request->response+used,request->response_capacity-used,"\"}");
        return;
    }

static __attribute__((noinline)) void management_wifi_set(micros_management_request_t *request) {
        /* Serial clients can submit two bounded profiles; the shared record keeps
         * the same four-slot representation used by the HTTP transport. */
        uint8_t settings[MICROS_WIFI_SETTINGS_BYTES]={0};
        if(request->body_bytes==204) {
            memcpy(settings,request->body,204);
            request->result=micros_wifi_settings_write(settings,sizeof(settings));
        } else request->result=micros_wifi_settings_write(request->body,request->body_bytes);
        memset(settings,0,sizeof(settings));
        snprintf(request->response, request->response_capacity, request->result == 0 ?
                 "{\"ok\":true}" : "{\"error\":\"Wi-Fi settings not saved; board busy, invalid list, or storage failure\"}");
        return;
    }

static __attribute__((noinline)) int management_relay_set(micros_management_request_t *request) {
 int okay;
        char settings[256];
        okay=request->body_bytes>0 && request->body_bytes<sizeof(settings) && !memchr(request->body,0,request->body_bytes);
        if(okay) {
            memcpy(settings,request->body,request->body_bytes);settings[request->body_bytes]=0;
            char host[128],token[65],extra;unsigned port;
            okay=sscanf(settings,"%127s %u %64s %c",host,&port,token,&extra)==3 && port>0 && port<=65535 &&
                 micros_network_configure_relay(host,port,token)==0;
            memset(token,0,sizeof(token));memset(settings,0,sizeof(settings));
        }
return okay;
}

static void management_request(micros_management_request_t *request)
{
    int okay = 1;
    if (request->operation == MICROS_MANAGEMENT_STATUS) { management_status(request);return; }
    if (request->operation == MICROS_MANAGEMENT_LOGS) { management_logs(request);return; }
    if (request->operation == MICROS_MANAGEMENT_PLATFORM_COMMAND) { management_platform_command(request);return; }
    if (request->operation == MICROS_MANAGEMENT_WIFI_GET) {
        request->result = micros_wifi_settings_read(request->response, request->response_capacity) ? 0 : -1;
        if (request->result) snprintf(request->response, request->response_capacity, "{\"error\":\"Wi-Fi unavailable\"}");
        return;
    }
    if (deployment_deadline && micros_platform_now_us() >= deployment_deadline) {
        if (micros_network_fetch_busy()) deployment_deadline=micros_platform_now_us()+DEPLOYMENT_SESSION_US;
        else finish_deployment_session();
    }
    if (request->operation == MICROS_MANAGEMENT_SESSION_BEGIN) {
        micros_activation_record_t selected = micros_storage_selection();
        uint32_t expected_sequence = 0;
        if (request->body_bytes == MICROS_ACTIVATION_HASH_BYTES + sizeof(expected_sequence))
            memcpy(&expected_sequence, request->body + MICROS_ACTIVATION_HASH_BYTES, sizeof(expected_sequence));
        okay = request->session[0] && !selected.pending && !physical_recovery &&
               (!deployment_session[0] || !strcmp(deployment_session, request->session)) &&
               request->body_bytes == MICROS_ACTIVATION_HASH_BYTES + sizeof(expected_sequence) &&
               expected_sequence == selected.sequence &&
               !memcmp(selected.good_hash, request->body, MICROS_ACTIVATION_HASH_BYTES);
        if (okay) {
            if (!deployment_session[0]) {
                deployment_previous = selected;
                deployment_stopped = 0;
            }
            memcpy(deployment_session, request->session, sizeof(deployment_session));
            deployment_deadline = micros_platform_now_us() + DEPLOYMENT_SESSION_US;
        }
        request->result = okay ? 0 : -1;
        snprintf(request->response, request->response_capacity, okay ? "{\"ok\":true}" :
                 "{\"error\":\"deployment session busy, selection changed, or physical recovery required\"}");
        return;
    }
    if (!deployment_session[0] || strcmp(deployment_session, request->session)) {
        request->result = -1;
        snprintf(request->response, request->response_capacity, "{\"error\":\"deployment session required or expired\"}");
        return;
    }
    deployment_deadline = micros_platform_now_us() + DEPLOYMENT_SESSION_US;
    if (micros_network_fetch_busy()) {
        request->result=-1;
        snprintf(request->response,request->response_capacity,"{\"error\":\"base download in progress\"}");
        return;
    }
    if (request->operation == MICROS_MANAGEMENT_BASE_FETCH) {
        char digest[65];
        okay=request->body_bytes==32 && micros_base_busy();
        if(okay) {
            for(unsigned i=0;i<32;++i)snprintf(digest+2*i,3,"%02x",request->body[i]);
            okay=micros_network_fetch_base(request->session,digest);
        }
        request->result=okay?0:-1;
        snprintf(request->response,request->response_capacity,"{\"ok\":%s}",okay?"true":"false");
        return;
    }
    if (request->operation == MICROS_MANAGEMENT_SESSION_END) {
        finish_deployment_session();
        snprintf(request->response, request->response_capacity, "{\"ok\":true}");
        return;
    }
    if (request->operation >= MICROS_MANAGEMENT_BASE_BEGIN && request->operation <= MICROS_MANAGEMENT_BASE_ABORT) {
        switch (request->operation) {
        case MICROS_MANAGEMENT_BASE_BEGIN:
            okay = !micros_storage_selection().pending && stop_graph();
            if (okay) {
                deployment_stopped=1;
                okay=micros_base_begin(request->body, request->body_bytes);
            }
            break;
        case MICROS_MANAGEMENT_BASE_CHUNK:
            okay = micros_base_chunk(request->log_cursor, request->body, request->body_bytes);
            break;
        case MICROS_MANAGEMENT_BASE_FINISH:
            okay = micros_base_finish();
            if (okay) management_reboot_us = micros_platform_now_us() + UINT64_C(2000000);
            break;
        case MICROS_MANAGEMENT_BASE_CONFIRM:
            okay = request->body_bytes == 32 &&
                   !memcmp(request->body, micros_controller_base_hash(), 32) &&
                   !physical_recovery && micros_platform_now_us() >= HEALTH_WINDOW_US &&
                   micros_base_confirm();
            break;
        case MICROS_MANAGEMENT_BASE_ABORT:
            micros_base_abort(); okay = 1; break;
        default: okay = 0;
        }
        request->result = okay ? 0 : -1;
        snprintf(request->response, request->response_capacity, okay ? "{\"ok\":true}" :
                 "{\"error\":\"base OTA rejected: inspect status and upload offset\"}");
        return;
    }
    if (micros_base_pending() || micros_base_busy() || selective.active) {
        request->result = -1;
        snprintf(request->response, request->response_capacity, "{\"error\":\"base update in progress\"}");
        return;
    }
    if (request->operation >= MICROS_MANAGEMENT_IMAGE_BEGIN && request->operation <= MICROS_MANAGEMENT_GRAPH_FINISH) {
        int graph_operation=request->operation>=MICROS_MANAGEMENT_GRAPH_BEGIN;
        unsigned operation=(unsigned)request->operation-(graph_operation?MICROS_MANAGEMENT_GRAPH_BEGIN:MICROS_MANAGEMENT_IMAGE_BEGIN);
        okay=0;
        if(operation==0 && request->body_bytes==4 && !transfer.active && request->bank<2 && request->slot<4) {
            uint32_t total;memcpy(&total,request->body,4);
            okay=graph_operation?total==sizeof(micros_device_graph_t):total>=64 && total<=MICROS_BOARD_IMAGE_BYTES;
            if(okay && live_flash_pause()) {
                okay=prepare_store(request->bank);live_flash_resume();
            } else okay=0;
            if(okay) {
                transfer.bank=request->bank;transfer.slot=request->slot;transfer.total=total;
                transfer.written=0;transfer.active=1;
                if(graph_operation) { transfer.graph=malloc(sizeof(*transfer.graph));okay=transfer.graph!=NULL; }
                if(!okay)transfer_abort();
            }
        } else if(operation==1 && transfer.active && !!transfer.graph==graph_operation &&
                  transfer.bank==request->bank && transfer.slot==request->slot &&
                  request->log_cursor==transfer.written && request->body_bytes &&
                  request->body_bytes<=256 && request->body_bytes<=transfer.total-transfer.written &&
                  (graph_operation || request->body_bytes%64==0 || transfer.written+request->body_bytes==transfer.total)) {
            if(graph_operation) {
                memcpy((uint8_t*)transfer.graph+transfer.written,request->body,request->body_bytes);okay=1;
            } else if(live_flash_pause()) {
                okay=micros_storage_write_image_part(transfer.bank,transfer.slot,transfer.written,request->body,request->body_bytes);
                live_flash_resume();
            }
            if(okay)transfer.written+=request->body_bytes;
        } else if(operation==2 && transfer.active && !!transfer.graph==graph_operation &&
                  transfer.bank==request->bank && transfer.slot==request->slot && transfer.written==transfer.total && !request->body_bytes) {
            if(graph_operation) {
                okay=transfer.graph->bank==transfer.bank && valid_graph(transfer.graph);
                if(okay && live_flash_pause()) {
                    okay=micros_storage_write_graph(transfer.bank,transfer.graph);live_flash_resume();
                } else okay=0;
            } else {
                char path[FILE_PATH_BYTES];image_path(path,transfer.bank,transfer.slot);
                okay=!micros_board_validate_image(path,transfer.slot);
            }
            transfer_abort();
        }
        request->result=okay?0:-1;
        snprintf(request->response,request->response_capacity,"{\"result\":%d}",request->result);
        return;
    }
    if (request->operation == MICROS_MANAGEMENT_WIFI_SET) { management_wifi_set(request);return; }
    if (request->operation == MICROS_MANAGEMENT_RELAY_SET) {
        okay=management_relay_set(request);
    } else if (request->operation == MICROS_MANAGEMENT_BOOTLOADER) {
        okay=MICROS_CAP_USB_BOOTLOADER && request->physical && stop_graph();
        if(okay)management_bootloader_us=micros_platform_now_us()+UINT64_C(500000);
    } else if (request->operation == MICROS_MANAGEMENT_BASE_ROLLBACK) {
        okay=stop_graph() && micros_base_rollback();
        if(okay)management_reboot_us=micros_platform_now_us()+UINT64_C(2000000);
    } else if (request->operation == MICROS_MANAGEMENT_ROLLBACK) {
        okay=activate_bank(micros_storage_selection().previous);
    } else if (request->operation == MICROS_MANAGEMENT_PAUSE) {
        okay = stop_graph();
        deployment_stopped = 0; /* Explicit operator pause persists until recover or reboot. */
    } else if (request->operation == MICROS_MANAGEMENT_IMAGE) {
        okay = micros_board_validate_bytes(request->body, request->body_bytes,
                                                       request->slot) == MICROS_OK;
        if (okay && (okay = live_flash_pause())) {
            okay = prepare_store(request->bank) && micros_storage_write_image(request->bank, request->slot, request->body,
                                              request->body_bytes);
            live_flash_resume();
        }
    } else if (request->operation == MICROS_MANAGEMENT_GRAPH) {
        okay = request->body_bytes == sizeof(micros_device_graph_t);
        micros_device_graph_t *graph=okay?malloc(sizeof(*graph)):NULL;
        okay=graph!=NULL;
        if (okay) {
            memcpy(graph,request->body,sizeof(*graph));
            okay=graph->bank==request->bank && valid_graph(graph);
            if(okay && (okay=live_flash_pause())) {
                okay=micros_storage_write_graph(request->bank,graph);live_flash_resume();
            }
        }
        free(graph);
    } else if (request->operation == MICROS_MANAGEMENT_ACTIVATE) {
        uint8_t actual_hash[MICROS_ACTIVATION_HASH_BYTES];
        okay = request->body_bytes == sizeof(actual_hash) &&
               micros_deployment_hash(request->bank, actual_hash) &&
               !memcmp(actual_hash, request->body, sizeof(actual_hash));
        if (okay)
            okay = activate_bank(request->bank);
    } else if (request->operation == MICROS_MANAGEMENT_STOP) {
        okay = stop_graph();
        deployment_stopped = 1;
    } else if (request->operation == MICROS_MANAGEMENT_REBOOT)
        management_reboot_us = micros_platform_now_us() +
                               UINT64_C(500000); /* Allow TLS reply to leave before resetting. */
    else
        okay = 0;
    request->result = okay ? 0 : -1;
    snprintf(request->response, request->response_capacity,
             okay ? "{\"ok\":true}" : "{\"error\":\"service-store operation rejected\"}");
}
/* Transport framing is common to serial, pipes and relay connections. */
static char *rpc_error(const char *message) {
 size_t bytes=strlen(message)+1;char *reply=malloc(bytes);
 if(reply)memcpy(reply,message,bytes);
 return reply;
}
/* The caller owns one reply buffer. Network transports retain it until their
 * acknowledgement; serial releases it immediately. Never copy a 4 KiB reply. */
char *micros_controller_rpc_reply(char *line, int physical) {
 unsigned operation=0,bank=0,slot=0;uint64_t cursor=0;char session[33]={0};int used=0;
 if(sscanf(line,"RPC %u %u %u %" SCNu64 " %32s %n",&operation,&bank,&slot,&cursor,session,&used)!=5 ||
    !used || operation>MICROS_MANAGEMENT_ROLLBACK || bank>=2 || slot>=4)
  return rpc_error("{\"result\":-1,\"error\":\"invalid RPC frame\"}");
 const char *hex=line+used;size_t length=!strcmp(hex,"-")?0:strlen(hex);
 if(length%2 || length>512 || (strcmp(session,"-") && (strlen(session)!=32 || strspn(session,"0123456789abcdef")!=32)))
  return rpc_error("{\"result\":-1}");
 uint8_t body[256];
 for(size_t i=0;i<length/2;++i) {
  int hi=micros_ipc_hex(hex[i*2]),lo=micros_ipc_hex(hex[i*2+1]);
  if(hi<0 || lo<0)return rpc_error("{\"result\":-1}");
  body[i]=(uint8_t)((hi<<4)|lo);
 }
 size_t capacity=operation==MICROS_MANAGEMENT_STATUS || (operation==MICROS_MANAGEMENT_PLATFORM_COMMAND && length/2>=10 && !memcmp(body,"IPC DRAIN ",10)) ?
   MICROS_MANAGEMENT_RESPONSE_BYTES : operation==MICROS_MANAGEMENT_WIFI_GET || operation==MICROS_MANAGEMENT_LOGS || operation==MICROS_MANAGEMENT_PLATFORM_COMMAND ? 1024 : 128;
 char *reply=calloc(1,capacity+32);
 if(!reply)return NULL;
 micros_management_request_t value={.response=reply+32,.response_capacity=capacity};
 micros_management_request_t *request=&value;
 request->physical=physical;
 request->operation=(micros_management_operation_t)operation;request->bank=bank;request->slot=slot;
 request->log_cursor=cursor;request->body=body;request->body_bytes=length/2;
 if(strcmp(session,"-"))memcpy(request->session,session,33);
 management_request(request);
 if(request->response[0]=='{' && strncmp(request->response,"{\"result\":",10)) {
  size_t prefix=(size_t)snprintf(reply,32,"{\"result\":%d,",request->result);
  memmove(reply+prefix,request->response+1,strlen(request->response));
 } else memmove(reply,request->response,strlen(request->response)+1);
 memset(body,0,sizeof(body));
 return reply;
}
void micros_controller_remote_line(char *line, int physical) {
 char *reply=micros_controller_rpc_reply(line,physical);
 if(reply){micros_transport_write(reply,strlen(reply));free(reply);}
 else micros_transport_write("{\"result\":-5}",13);
 micros_transport_write("\n",1);
}

static void management_poll(void)
{
    if (deployment_deadline && micros_platform_now_us() >= deployment_deadline) {
        if (micros_network_fetch_busy()) deployment_deadline=micros_platform_now_us()+DEPLOYMENT_SESSION_US;
        else finish_deployment_session();
    }
    micros_management_poll();
    if (management_bootloader_us && micros_platform_now_us() >= management_bootloader_us)
        micros_controller_bootloader();
    if (management_reboot_us && micros_platform_now_us() >= management_reboot_us)
        micros_controller_reset();
}

#include "protocol/runtime_commands.inc"

/** @brief Inspect recovery wiring before boot; release the graph-sized stack frame
 * before loading services or entering the long-lived controller loop. */
static __attribute__((noinline)) int recovery_input_pin(void)
{
    /* A confirmed, CRC-checked graph owns boot recovery wiring too. Before the
     * first graph migration, retain the physically provisioned fallback input. */
    micros_activation_record_t selection=micros_storage_selection();
    micros_device_graph_t recovery_graph;
    int recovery_pin=MICROS_BOARD_RECOVERY_GPIO;
    if (selection.good<MICROS_GRAPH_BANKS && micros_storage_read_graph(selection.good,&recovery_graph) && valid_graph(&recovery_graph))
        recovery_pin=recovery_graph.recovery_line==UINT32_MAX ? -1 : (int)recovery_graph.gpio[recovery_graph.recovery_line].pin;
    return recovery_pin;
}

static __attribute__((noinline)) void physical_command(char *command,int overflow)
{
        unsigned bank, slot, bytes, boundary;
        if (overflow)
            printf("REJECT command length\n");
        else if (micros_base_pending() || micros_base_busy())
            printf("REJECT base update in progress; use authenticated management\n");
        else if (!strncmp(command, "IPC ", 4)) {
            char reply[600];
            size_t reply_capacity=sizeof(reply);
            micros_ipc_command(runtime, instances, instance_count, command,reply,reply_capacity);
            puts(reply);
        }
        else if (!strncmp(command, "WIFI ", 5))
            micros_wifi_command(command);
        else if (!strcmp(command, "INFO") || !strcmp(command, "STATUS"))
            report_status();
        else if (sscanf(command, "FAULT %u", &boundary) == 1) {
            micros_storage_fault_arm(boundary);
            printf("FAULT ARMED %u\n", boundary);
        } else if (!strcmp(command, "RESUME")) {
            physical_recovery = 0;
            printf("RESUMED\n");
        } else if (!strcmp(command, "STOP"))
            printf("STOPPED %s\n", stop_graph() ? "OK" : "REJECT");
        else if (!strcmp(command, "REBOOT")) {
            printf("REBOOTING\n");
            fflush(stdout);
            micros_controller_reset();
        } else if (sscanf(command, "IMAGE %u %u %u", &bank, &slot, &bytes) == 3) {
            if (runtime || bank >= MICROS_GRAPH_BANKS || slot >= MICROS_BOARD_IMAGE_SLOTS ||
                bytes < MICROS_IMAGE_HEADER_BYTES || bytes > MICROS_BOARD_IMAGE_BYTES) {
                printf("REJECT image admission; stop graph before transfer\n");
                return;
            }
            uint8_t *image = micros_controller_transfer_allocate(bytes);
            if (!image) {
                printf("REJECT staging capacity\n");
                return;
            }
            printf("READY %u\n", bytes);
            fflush(stdout);
            int okay = read_exact(image, bytes) &&
                       micros_board_validate_bytes(image, bytes, slot) == MICROS_OK;
            if (okay)
                okay = prepare_store(bank) && micros_storage_write_image(bank, slot, image, bytes);
            free(image);
            printf("IMAGE %s\n", okay ? "OK" : "REJECT");
        } else if (sscanf(command, "CONFIG %u %u", &bank, &bytes) == 2) {
            if (runtime || bank >= MICROS_GRAPH_BANKS || bytes != sizeof(micros_device_graph_t)) {
                printf("REJECT graph length/state\n");
                return;
            }
            micros_device_graph_t *graph=malloc(sizeof(*graph));
            if(!graph) { printf("REJECT staging capacity\n");return; }
            printf("READY %u\n", bytes);
            fflush(stdout);
            int okay=read_exact(graph,sizeof(*graph)) && graph->bank==bank && valid_graph(graph);
            if(okay)okay=micros_storage_write_graph(bank,graph);
            free(graph);
            printf("CONFIG %s\n", okay ? "OK" : "REJECT");
        } else if (sscanf(command, "BOOT %u", &bank) == 1) {
            int okay = activate_bank(bank);
            printf("BOOT %s\n", okay ? "OK" : "REJECT");
        } else
            printf("REJECT command\n");
}

void micros_controller_run(void)
{
    micros_controller_initialize(&service_boot);
    micros_base_boot();
    if (!micros_storage_init()) {
        controller_event("FATAL service storage unavailable\n");
        return;
    }
    int recovery_pin=recovery_input_pin();
    physical_recovery = recovery_pin >= 0 && micros_controller_recovery_pressed(recovery_pin);

    baseline_heap = micros_controller_heap_free();

    micros_management_start(management_request);
    micros_activation_record_t boot_selection = micros_storage_selection();
    if (!physical_recovery && micros_base_application_allowed(
            boot_selection.pending ? boot_selection.candidate_hash : boot_selection.good_hash))
        activation_boot();
    for (;;) {
        recover_if_needed();
        poll_health();
        management_poll();
        static char command[COMMAND_BYTES];
        size_t length = 0;
        int overflow = 0;
        for (;;) {
            uint8_t byte;
            int received=micros_controller_read(&byte, 1, 100);
            if (received<0) { stop_graph();return; }
            if (received != 1) {
                recover_if_needed();
                poll_health();
                management_poll();
                continue;
            }
            if (byte == '\n')
                break;
            if (byte == '\r')
                continue;
            if (length < sizeof(command) - 1)
                command[length++] = byte;
            else
                overflow = 1;
        }
        command[length] = 0;
        if (!overflow && !strncmp(command,"RPC ",4)) { micros_controller_remote_line(command, 1);memset(command,0,sizeof(command));continue; }
        int handled=overflow ? 0 : runtime_command(command);
        if (handled==2) return;
        if (handled) continue;
        physical_command(command,overflow);
        memset(command, 0, sizeof(command)); /* Do not retain USB passwords on the controller stack. */
        fflush(stdout);
    }
}
