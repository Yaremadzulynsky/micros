#include <micros/memory.h>
#ifndef MICROS_SELECTIVE_DEPLOY_H
#define MICROS_SELECTIVE_DEPLOY_H
/* Native peers retain RAM, handles and identity. The only shared interruption
 * is a quiescent MMU switch; both banks contain identical bytes for those peers. */
/* Flash erases suspend cache-backed execution. Quiesce native hooks so that
 * storage latency cannot consume a service's execution deadline. */
static int live_flash_pause(void)
{
    if (!runtime || !micros_runtime_pause(runtime)) return 1;
    recover_if_needed();
    return 0;
}
static void live_flash_resume(void)
{
    if (runtime) micros_runtime_resume(runtime);
}
static int live_select(micros_activation_record_t record, int bind)
{
    if (!live_flash_pause()) return 0;
    int okay = (!bind || micros_base_bind_application(record.candidate, record.candidate_hash)) &&
               micros_storage_select(record);
    live_flash_resume();
    return okay;
}
#if MICROS_CAP_SELECTIVE_UPDATE
static struct {
    int active;
    unsigned previous_bank;
    uint32_t changed;
    micros_device_graph_t previous;
} selective;

static int selective_stop_changed(void)
{
    for (unsigned i = 0; i < instance_count; ++i) {
        if (!(selective.changed & (1u << i)) || !instances[i]) continue;
        (void)micros_runtime_stop(runtime, instances[i]);
        recover_if_needed();
        if (micros_runtime_unload(runtime, instances[i])) return 0;
        instances[i] = 0;
    }
    return 1;
}
static int selective_switch(unsigned bank)
{
    if (micros_runtime_pause(runtime)) { recover_if_needed(); return 0; }
    int result = micros_storage_rebind_images(bank);
    /* A broken alias cannot be exposed even briefly to preserved workers. */
    if (result < 0) { micros_controller_reset(); return 0; }
    micros_runtime_resume(runtime);
    return result;
}
static int selective_load(unsigned bank, const micros_device_graph_t *graph)
{
    for (unsigned i = 0; i < instance_count; ++i) {
        if (!(selective.changed & (1u << i))) continue;
        const micros_graph_service_t *s = &graph->services[i];
        micros_resource_policy_t policy = {s->timers, s->gpio_mask, s->publish_mask, s->subscribe_mask};
        char path[FILE_PATH_BYTES];
        image_path(path, bank, s->slot);
        if (micros_runtime_load(runtime, path, s->handles, &instances[i]) ||
            micros_runtime_set_config(runtime, instances[i], graph->configurations[i].data,
                                     graph->configurations[i].bytes) ||
            micros_runtime_set_policy(runtime, instances[i], &policy)) return 0;
        micros_service_status_t status = {0};
        if (micros_runtime_status(runtime, instances[i], &status) ||
            status.arena_bytes != s->arena_bytes || status.arena_alignment != s->arena_alignment ||
            status.stack_bytes != s->stack_bytes) return 0;
    }
    /* Complete admission before entering any changed service's native hooks. */
    for (unsigned i = 0; i < instance_count; ++i)
        if ((selective.changed & (1u << i)) && micros_runtime_start(runtime, instances[i])) return 0;
    return 1;
}
static int selective_restore(void)
{
    micros_activation_record_t record = micros_storage_selection();
    clear_trial(&record);
    /* A reset during local rollback must boot the original, intact good bank. */
    if (!live_select(record, 0) || !selective_stop_changed() ||
        !selective_switch(selective.previous_bank) ||
        !selective_load(selective.previous_bank, &selective.previous)) {
        micros_controller_reset(); return 0;
    }
    running_bank = (int)selective.previous_bank;
    health_deadline_us = 0;
    selective.active = 0;
    controller_event("SELECTIVE ROLLBACK bank=%u\n", selective.previous_bank);
    return 1;
}
/* 0: shared layout requires complete activation; -1: rejected; 1: trial started.
 * All validation and exact-byte comparison finish before any worker is stopped. */
static int selective_begin(unsigned bank, const micros_device_graph_t *next)
{
    if (!MICROS_CAP_SELECTIVE_UPDATE) return 0;
    micros_activation_record_t record = micros_storage_selection();
    if (!runtime || running_bank != (int)record.good || instance_count != next->service_count ||
        !load_graph(record.good, &selective.previous)) return 0;
    const micros_device_graph_t *old = &selective.previous;
    if (old->channel_count != next->channel_count ||
        memcmp(old->channels, next->channels, sizeof(old->channels)) ||
        old->gpio_count != next->gpio_count || old->recovery_line != next->recovery_line ||
        memcmp(old->gpio, next->gpio, sizeof(old->gpio))) return 0;
    for (unsigned i = 0; i < instance_count; ++i) {
        micros_service_status_t status = {0};
        if (old->services[i].slot != next->services[i].slot ||
            micros_runtime_status(runtime, instances[i], &status) ||
            status.state != MICROS_STATE_RUNNING || status.result) return 0;
    }
    selective.changed = 0;
    for (unsigned i = 0; i < instance_count; ++i) {
        size_t old_bytes = 0, new_bytes = 0;
        unsigned slot = next->services[i].slot;
        uint8_t *before = micros_storage_read_image(record.good, slot, &old_bytes);
        uint8_t *after = micros_storage_read_image(bank, slot, &new_bytes);
        int valid = before && after && !micros_board_validate_bytes(after, new_bytes, slot);
        int changed = !valid || old_bytes != new_bytes || memcmp(before, after, old_bytes) ||
            memcmp(&old->services[i], &next->services[i], sizeof(old->services[i])) ||
            memcmp(&old->configurations[i], &next->configurations[i], sizeof(old->configurations[i]));
        micros_management_free(before); micros_management_free(after);
        if (!valid) return -1;
        if (changed) selective.changed |= 1u << i;
    }
    if (!micros_deployment_hash(bank, record.candidate_hash)) return -1;
    record.candidate = bank;
    record.pending = 1;
    record.attempts = 1; /* This live transition is the first durable trial attempt. */
    record.previous = MICROS_ACTIVATION_NONE;
    memset(record.previous_hash, 0, sizeof(record.previous_hash));
    if (!live_select(record, 1)) return -1;
    selective.previous_bank = (unsigned)running_bank;
    selective.active = 1;
    micros_storage_fault_boundary(10);
    if (!selective_stop_changed() || !selective_switch(bank) || !selective_load(bank, next)) {
        selective_restore();
        return 1; /* Status, not the acknowledgement, decides rollback versus commit. */
    }
    running_bank = (int)bank;
    health_deadline_us = micros_platform_now_us() + HEALTH_WINDOW_US;
    controller_event("SELECTIVE TRIAL changed_mask=%u bank=%u\n", (unsigned)selective.changed, bank);
    return 1;
}
#else
/* Unsupported live replacement carries no retained graph or image buffers. */
static struct { int active;uint32_t changed; } selective;
static int selective_begin(unsigned bank,const micros_device_graph_t *graph) { (void)bank;(void)graph;return 0; }
static int selective_restore(void) { return 0; }
#endif
#endif
