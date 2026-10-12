#include <micros/capabilities.h>
MICROS_REQUIRE_CAPABILITY(NATIVE_SERVICES);
#include "FreeRTOS.h"
#include "support/hardware.h"
#include "image.h"
#include "semphr.h"
#include "support/storage.h"
#include "task.h"
#include <malloc.h>
#include <micros/platform.h>
#include <stdlib.h>
#include <string.h>

typedef struct waiter
{
    TaskHandle_t task;
    struct waiter *next;
} waiter_t;
struct micros_platform_sync
{
    SemaphoreHandle_t mutex;
    waiter_t *waiters;
    StaticSemaphore_t storage;
    int owned;
};
struct micros_platform_task
{
    TaskHandle_t task;
    SemaphoreHandle_t done;
    void *(*entry)(void *);
    void *argument;
    StaticTask_t task_storage;
    StaticSemaphore_t done_storage;
    int owned;
};
struct micros_platform_gpio
{
    uint32_t lines;
};
struct micros_platform_image
{
    const micros_service_descriptor_t *descriptor;
    uint32_t slot;
};
static uint32_t loaded_slots;

#define MICROS_MEMORY_PANIC micros_samd21_panic
#include "../../../kernel/support/static_memory.inc"
static micros_platform_gpio_t static_gpio;
static int gpio_owned;
static micros_platform_sync_t static_sync;
static micros_platform_task_t static_tasks[5];
static micros_platform_image_t static_images[4];
static _Alignas(16) StackType_t supervisor_stack[MICROS_CONTROLLER_SUPERVISOR_STACK / sizeof(StackType_t)];

micros_platform_gpio_t *micros_platform_gpio_create(uint32_t lines)
{
    if (lines != 4)
        return NULL;
    if (gpio_owned) return NULL;
    gpio_owned = 1;
    micros_platform_gpio_t *gpio = &static_gpio;
    if (gpio)
    {
        gpio->lines = lines;
    }
    return gpio;
}
void micros_platform_gpio_destroy(micros_platform_gpio_t *gpio) { gpio_owned = 0; (void)gpio; }
micros_result_t micros_platform_gpio_read(micros_platform_gpio_t *gpio, uint32_t line,
                                          uint32_t *level)
{
    if (!gpio || line >= gpio->lines || !level)
        return MICROS_ERROR_INVALID_ARGUMENT;
    *level = embedded_gpio_read(line);
    return MICROS_OK;
}
micros_result_t micros_platform_gpio_write(micros_platform_gpio_t *gpio, uint32_t line,
                                           uint32_t level)
{
    if (!gpio || line >= gpio->lines || level > 1)
        return MICROS_ERROR_INVALID_ARGUMENT;
    if (!embedded_gpio_write(line, level))
        return MICROS_ERROR_INVALID_ARGUMENT;
    return MICROS_OK;
}
micros_platform_sync_t *micros_platform_sync_create(void)
{
    if (static_sync.owned) return NULL;
    micros_platform_sync_t *sync = &static_sync;
    memset(sync, 0, sizeof(*sync));
    sync->owned = 1;
    if (sync && !(sync->mutex = xSemaphoreCreateMutexStatic(&sync->storage)))
    {
        sync->owned = 0;
        return NULL;
    }
    return sync;
}
void micros_platform_sync_destroy(micros_platform_sync_t *sync)
{
    configASSERT(!sync->waiters);
    vSemaphoreDelete(sync->mutex);
    sync->owned = 0;
}
void micros_platform_lock(micros_platform_sync_t *sync)
{
    configASSERT(xSemaphoreTake(sync->mutex, portMAX_DELAY) == pdTRUE);
}
void micros_platform_unlock(micros_platform_sync_t *sync)
{
    configASSERT(xSemaphoreGive(sync->mutex) == pdTRUE);
}
void micros_platform_notify(micros_platform_sync_t *sync)
{
    /* Called with the mutex held; notify every registered waiter, not just one. */
    for (waiter_t *w = sync->waiters; w; w = w->next)
        xTaskNotifyGive(w->task);
}
uint64_t micros_platform_now_us(void) { return micros_samd21_clock_us(); }
void micros_platform_wait(micros_platform_sync_t *sync, uint64_t deadline)
{
    uint64_t now = micros_platform_now_us();
    if (deadline <= now)
        return;
    uint64_t ticks = (deadline - now) / 1000 + ((deadline - now) % 1000 != 0);
    if (ticks >= portMAX_DELAY)
        ticks = portMAX_DELAY - 1;
    (void)ulTaskNotifyTake(pdTRUE, 0);
    waiter_t waiter = {xTaskGetCurrentTaskHandle(), sync->waiters};
    sync->waiters = &waiter;
    micros_platform_unlock(sync);
    (void)ulTaskNotifyTake(pdTRUE, (TickType_t)ticks);
    micros_platform_lock(sync);
    waiter_t **link = &sync->waiters;
    while (*link != &waiter)
        link = &(*link)->next;
    *link = waiter.next;
}
size_t micros_platform_stack_bytes(size_t bytes)
{
    return bytes > SIZE_MAX - 7 ? SIZE_MAX : ((bytes < 512 ? 512 : bytes) + 7) & ~(size_t)7;
}
size_t micros_platform_task_metadata_bytes(void)
{
    return sizeof(micros_platform_task_t);
}
size_t micros_platform_metadata_bytes(uint32_t lines)
{
    (void)lines;
    return sizeof(micros_platform_gpio_t) + sizeof(micros_platform_sync_t);
}
static void run_task(void *argument)
{
    micros_platform_task_t *task = argument;
    task->entry(task->argument);
    xSemaphoreGive(task->done);
    /* The joiner owns deletion, so stack-watermark inspection remains valid. */
    vTaskSuspend(NULL);
    micros_samd21_panic();
}
static micros_platform_task_t *create_task(void *(*entry)(void *), void *argument,
    size_t bytes, UBaseType_t priority, void *stack, unsigned first, unsigned end)
{
    if (!entry || !stack || bytes != micros_platform_stack_bytes(bytes)) return NULL;
    micros_platform_task_t *task = NULL;
    for (unsigned i = first; i < end; ++i)
        if (!static_tasks[i].owned) { task = &static_tasks[i]; break; }
    if (!task) return NULL;
    memset(task, 0, sizeof(*task));
    task->owned = 1;
    task->entry = entry;
    task->argument = argument;
    task->done = xSemaphoreCreateBinaryStatic(&task->done_storage);
    task->task = xTaskCreateStatic(run_task, "micros", bytes / sizeof(StackType_t),
        task, priority, stack, &task->task_storage);
    if (!task->task) {
        vSemaphoreDelete(task->done);
        task->owned = 0;
        return NULL;
    }
    return task;
}
micros_platform_task_t *micros_platform_task_create_with_stack(void *(*entry)(void *),
    void *argument, size_t bytes, void *stack)
{ return create_task(entry, argument, bytes, 1, stack, 0, 4); }
micros_platform_task_t *micros_platform_task_create(void *(*entry)(void *),
    void *argument, size_t bytes)
{
    /* All service callers on static targets must reserve their stack at admission. */
    (void)entry; (void)argument; (void)bytes;
    return NULL;
}
micros_platform_task_t *micros_platform_supervisor_create(void *(*entry)(void *),
    void *argument, size_t bytes)
{
    if (bytes > sizeof(supervisor_stack)) return NULL;
    return create_task(entry, argument, sizeof(supervisor_stack), 3, supervisor_stack, 4, 5);
}
void micros_platform_task_join(micros_platform_task_t *task)
{
    xSemaphoreTake(task->done, portMAX_DELAY);
    vTaskDelete(task->task);
    vSemaphoreDelete(task->done);
    task->owned = 0;
}
size_t micros_platform_stack_free(micros_platform_task_t *task)
{
    return uxTaskGetStackHighWaterMark(task->task) * sizeof(StackType_t);
}
void *micros_platform_arena_allocate(size_t alignment, size_t bytes, uint32_t placement)
{
    if (placement || !alignment || (alignment & (alignment - 1)) || alignment > 16)
        return NULL;
    return micros_memory_allocate(bytes);
}
void micros_platform_debug_to_stderr(void) {}
micros_result_t micros_platform_debug(const uint8_t *bytes, uint32_t count)
{
    if ((!bytes && count) || count > MICROS_DEBUG_MAX_BYTES)
        return MICROS_ERROR_INVALID_ARGUMENT;
    embedded_log(bytes, count);
    return MICROS_OK;
}
micros_result_t micros_platform_image_open(const char *path, micros_platform_image_t **image,
                                           const micros_service_descriptor_t **descriptor,
                                           size_t *bytes)
{
    if (!path || !image || !descriptor || !bytes || strlen(path) != 3 || path[1] != ':' ||
        path[0] < '0' || path[0] > '1' || path[2] < '0' || path[2] > '3')
        return MICROS_ERROR_INVALID_ARGUMENT;
    uint32_t bank = path[0] - '0', slot = path[2] - '0';
    if ((loaded_slots & (1u << slot)) || micros_board_validate_image(path,slot))
        return MICROS_ERROR_INVALID_ARGUMENT;
    uint32_t address = embedded_image_address(bank, slot);
    const uint32_t *header = (const void *)(uintptr_t)address;
    micros_platform_image_t *loaded = &static_images[slot];
    if (!loaded)
        return MICROS_ERROR_CAPACITY;
    memset(micros_samd21_data[slot], 0, SAMD_DATA_BYTES);
    memcpy(micros_samd21_data[slot], (const void *)(uintptr_t)(address + 64 + header[7]),
           header[8]);
    loaded->descriptor = (const void *)(micros_samd21_data[slot] + header[10]);
    loaded->slot = slot;
    loaded_slots |= 1u << slot;
    *image = loaded;
    *descriptor = loaded->descriptor;
    *bytes = header[7] + header[8];
    return MICROS_OK;
}
void micros_platform_image_close(micros_platform_image_t *image)
{
    loaded_slots &= ~(1u << image->slot);
    memset(micros_samd21_data[image->slot], 0, SAMD_DATA_BYTES);
    memset(image, 0, sizeof(*image));
}

void micros_platform_arena_free(void *arena) { micros_memory_free(arena); }

/* This target's service ABI has no analog implementation. Builds requiring
 * analog GPIO are rejected by the capability contract before linking. */
micros_result_t micros_platform_gpio_read_analog(micros_platform_gpio_t *gpio,
                                                uint32_t line, uint32_t *raw)
{ (void)gpio; (void)line; (void)raw; return MICROS_ERROR_UNSUPPORTED; }
void micros_platform_gpio_release(micros_platform_gpio_t *gpio, uint32_t line)
{ (void)gpio; (void)line; }

#include "device_support.h"
#include <micros/platform.h>
#include <micros/controller.h>
#include <micros/transport.h>
#include <micros/telemetry.h>
#include <stdlib.h>
static micros_graph_gpio_t controller_bindings[4];
static unsigned controller_binding_count;
void micros_controller_initialize(uint64_t *identity) {
 embedded_console_begin();*identity=micros_platform_now_us();
}
void micros_controller_reset(void) { embedded_reset(); }
unsigned micros_controller_reset_reason(void) { return embedded_reset_cause(); }
size_t micros_controller_heap_free(void) { return embedded_heap_free(); }
int micros_controller_gpio_level(int pin) {
 for(unsigned i=0;i<controller_binding_count;++i)if(controller_bindings[i].pin==(unsigned)pin)return (int)embedded_gpio_read(i);
 return 0;
}
int micros_controller_recovery_pressed(int pin) { return micros_controller_gpio_level(pin)==0; }
const uint8_t *micros_controller_base_hash(void) { static uint8_t hash[32];embedded_base_hash(hash);return hash; }
void *micros_controller_transfer_allocate(size_t bytes) { return micros_management_allocate(bytes); }
void micros_controller_yield(void) { embedded_idle();embedded_controller_wait(); }
int micros_board_recovery_pin(void) { return -1; }
int micros_board_validate_gpio(const micros_device_graph_t *graph) {
 if(graph->gpio_count>4 || (graph->recovery_line!=UINT32_MAX && graph->recovery_line>=graph->gpio_count))return 0;
 for(unsigned i=0;i<graph->gpio_count;++i) {
  if(!embedded_pin_valid(graph->gpio[i].pin) || graph->gpio[i].output>1)return 0;
  for(unsigned j=0;j<i;++j)if(graph->gpio[i].pin==graph->gpio[j].pin)return 0;
 }
 return 1;
}
int micros_board_apply_gpio(const micros_device_graph_t *graph) {
 if(!micros_board_validate_gpio(graph))return 0;
 for(unsigned i=0;i<4;++i)embedded_gpio_bind(i,i<graph->gpio_count?graph->gpio[i].pin:255,i<graph->gpio_count?graph->gpio[i].output:0);
 controller_binding_count=graph->gpio_count;memcpy(controller_bindings,graph->gpio,sizeof(controller_bindings));return 1;
}
unsigned micros_board_gpio_bindings(const micros_graph_gpio_t **bindings) { *bindings=controller_bindings;return controller_binding_count; }

void micros_controller_bootloader(void) { embedded_bootloader(); }

void micros_controller_identity(uint8_t identity[6]) { embedded_network_identity_bytes(identity); }

int micros_board_validate_bytes(const void *data,size_t bytes,unsigned slot) {
 micros_image_t image;
 if(slot>=4 || micros_image_validate(data,bytes,EMBEDDED_TARGET,&image))return MICROS_ERROR_INVALID_ARGUMENT;
 if((image.code_base!=embedded_image_address(0,slot)+64 && image.code_base!=embedded_image_address(1,slot)+64) ||
    image.data_base!=(uintptr_t)embedded_image_data(slot) || image.data_bytes>EMBEDDED_DATA_BYTES ||
    image.bss_bytes>EMBEDDED_DATA_BYTES-image.data_bytes)return MICROS_ERROR_CAPACITY;
 const uint32_t *descriptor=(const void *)((const uint8_t*)data+64+image.code_bytes+image.descriptor_offset);
 if(descriptor[0]!=48 || descriptor[1]!=MICROS_ABI_MAJOR || descriptor[2]!=MICROS_ABI_REVISION || descriptor[3]!=EMBEDDED_TARGET ||
    descriptor[4]>EMBEDDED_ARENA_BUDGET || !descriptor[5] || descriptor[5]>16 || (descriptor[5]&(descriptor[5]-1)) ||
    descriptor[6]<512 || descriptor[6]>EMBEDDED_STACK_BUDGET || descriptor[7])return MICROS_ERROR_INVALID_ARGUMENT;
 for(unsigned i=8;i<12;++i)if(!embedded_entry_valid(descriptor[i],image.code_base,image.code_bytes))return MICROS_ERROR_INVALID_ARGUMENT;
 return MICROS_OK;
}
int micros_board_validate_image(const char *path,unsigned slot) {
 if(!path || strlen(path)!=3 || path[0]<'0' || path[0]>'1' || path[1]!=':' || path[2]!=(char)('0'+slot))return MICROS_ERROR_INVALID_ARGUMENT;
 unsigned bank=(unsigned)(path[0]-'0');
 const uint32_t *header=(const void*)(uintptr_t)embedded_image_address(bank,slot);
 if(header[7]>EMBEDDED_SLOT_BYTES-64 || header[8]>EMBEDDED_SLOT_BYTES-64-header[7])return MICROS_ERROR_INVALID_ARGUMENT;
 return embedded_image_validate(bank,slot,64+header[7]+header[8])?MICROS_OK:MICROS_ERROR_INVALID_ARGUMENT;
}

void vApplicationGetIdleTaskMemory(StaticTask_t **tcb, StackType_t **stack, uint32_t *words)
{
    static StaticTask_t idle_tcb;
    static StackType_t idle_stack[configMINIMAL_STACK_SIZE];
    *tcb = &idle_tcb; *stack = idle_stack; *words = configMINIMAL_STACK_SIZE;
}
