#include <micros/capabilities.h>
MICROS_REQUIRE_CAPABILITY(NATIVE_SERVICES);
#include "support/board_profile.h"
#include <micros/platform.h>
#include <micros/capabilities.h>
#include <micros/controller.h>
#include "driver/gpio.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "image.h"
#include <micros/transport.h>
#include "support/storage.h"
#include <ctype.h>
#include <micros/platform.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/** @brief Mutex plus bounded task-notification waiters implementing broadcast conditions. */
struct micros_platform_sync {
    StaticSemaphore_t mutex_storage;
    SemaphoreHandle_t mutex;
    TaskHandle_t waiters[MICROS_BOARD_WAITERS];
};
/** @brief Static FreeRTOS task and stack, retained until the wrapper is parked and joined. */
struct micros_platform_task {
    StaticTask_t task_storage;
    TaskHandle_t task;
    StackType_t *stack;
    StaticSemaphore_t done_storage;
    SemaphoreHandle_t done;
    void *(*entry)(void *);
    void *argument;
};
/** @brief Active deployment GPIO count; access is limited by each service grant. */
struct micros_platform_gpio {
    uint32_t lines;
    adc_oneshot_unit_handle_t adc;
    uint32_t analog_lines;
};
/** @brief Claim on one linked code/data slot, preventing concurrent overwrite. */
struct micros_platform_image {
    unsigned slot;
};

#if CONFIG_MICROS_SERVICE_FLASH
extern const uint8_t micros_rodata_slot0[], micros_rodata_slot1[], micros_rodata_slot2[], micros_rodata_slot3[];
static const uint8_t *const rodata_slots[] = {micros_rodata_slot0, micros_rodata_slot1,
    micros_rodata_slot2, micros_rodata_slot3};
#endif
extern uint32_t micros_code_slot0[], micros_code_slot1[], micros_code_slot2[], micros_code_slot3[];
uint8_t micros_data_slot0[MICROS_BOARD_DATA_BYTES]
    __attribute__((aligned(MICROS_BOARD_SLOT_ALIGNMENT)));
uint8_t micros_data_slot1[MICROS_BOARD_DATA_BYTES]
    __attribute__((aligned(MICROS_BOARD_SLOT_ALIGNMENT)));
uint8_t micros_data_slot2[MICROS_BOARD_DATA_BYTES]
    __attribute__((aligned(MICROS_BOARD_SLOT_ALIGNMENT)));
uint8_t micros_data_slot3[MICROS_BOARD_DATA_BYTES]
    __attribute__((aligned(MICROS_BOARD_SLOT_ALIGNMENT)));
static uint32_t *const code_slots[] = {micros_code_slot0, micros_code_slot1, micros_code_slot2,
                                       micros_code_slot3};
static uint8_t *const data_slots[] = {micros_data_slot0, micros_data_slot1, micros_data_slot2,
                                      micros_data_slot3};
static int slot_claimed[MICROS_BOARD_IMAGE_SLOTS];

/** @brief Original provisioning fingerprint, retained for legacy tooling. */
const char micros_board_config_sha256[] = MICROS_BOARD_CONFIG_SHA256;
const uint32_t micros_board_gpio_count = MICROS_RUNTIME_GPIO_CAPACITY;
/* ELF capability marker lets tooling send graph-owned bindings without base migration. */
const uint32_t micros_board_dynamic_bindings = 1;
const uint32_t micros_board_flash_mb = MICROS_BOARD_FLASH_MB;
/** @brief Active graph-owned pin and direction for each service-visible logical line. */
static micros_graph_gpio_t board_gpio[MICROS_RUNTIME_GPIO_CAPACITY];
static unsigned board_gpio_lines;
static int board_recovery_pin=MICROS_BOARD_RECOVERY_GPIO;
int micros_board_recovery_pin(void) { return board_recovery_pin; }

int micros_board_validate_gpio(const micros_device_graph_t *graph)
{
    if (graph->gpio_count>MICROS_RUNTIME_GPIO_CAPACITY) return 0;
    if (graph->recovery_line != UINT32_MAX &&
        (graph->recovery_line >= graph->gpio_count || graph->gpio[graph->recovery_line].output)) return 0;
    uint64_t pins=0;
    for (unsigned line=0;line<MICROS_RUNTIME_GPIO_CAPACITY;++line) {
        const micros_graph_gpio_t *binding=&graph->gpio[line];
        if (line>=graph->gpio_count) {
            micros_graph_gpio_t zero={0};
            if (memcmp(binding,&zero,sizeof(zero))) return 0;
            continue;
        }
        int pin=(int)binding->pin;
        /* Flash and the resident serial controller cannot be reassigned by an app. */
        if (pin<0 || pin>39 || (pin>=6 && pin<=11) || pin==1 || pin==3 ||
            !GPIO_IS_VALID_GPIO(pin) || binding->output>1 ||
            (binding->output && !GPIO_IS_VALID_OUTPUT_GPIO(pin)) || (pins&(UINT64_C(1)<<pin))) return 0;
        pins|=UINT64_C(1)<<pin;
        size_t length=strnlen(binding->name,sizeof(binding->name));
        if (!length || length>32 || !(isalpha((unsigned char)binding->name[0]) || binding->name[0]=='_')) return 0;
        for (size_t byte=0;byte<length;++byte)
            if (!(isalnum((unsigned char)binding->name[byte]) || binding->name[byte]=='_')) return 0;
        for (size_t byte=length;byte<sizeof(binding->name);++byte)
            if (binding->name[byte]) return 0;
        for (unsigned previous=0;previous<line;++previous)
            if (!strcmp(binding->name,graph->gpio[previous].name)) return 0;
    }
    return 1;
}
int micros_board_apply_gpio(const micros_device_graph_t *graph)
{
    if (!micros_board_validate_gpio(graph)) return 0;
    memcpy(board_gpio,graph->gpio,sizeof(board_gpio));
    board_gpio_lines=graph->gpio_count;
    board_recovery_pin=graph->recovery_line==UINT32_MAX ? -1 : (int)graph->gpio[graph->recovery_line].pin;
    return 1;
}
unsigned micros_board_gpio_bindings(const micros_graph_gpio_t **bindings)
{
    *bindings=board_gpio;
    return board_gpio_lines;
}

micros_platform_gpio_t *micros_platform_gpio_create(uint32_t line_count)
{
    if (line_count != MICROS_RUNTIME_GPIO_CAPACITY)
        return NULL;
    micros_platform_gpio_t *gpio = calloc(1, sizeof(*gpio));
    if (!gpio)
        return NULL;
    for (uint32_t line = 0; line < board_gpio_lines; ++line) {
        int pin = board_gpio[line].pin;
        gpio_config_t configuration = {
            .pin_bit_mask = UINT64_C(1) << pin,
            .mode = board_gpio[line].output ? GPIO_MODE_INPUT_OUTPUT : GPIO_MODE_INPUT,
            .intr_type = GPIO_INTR_DISABLE,
        };
        if (!GPIO_IS_VALID_GPIO(pin) ||
            (board_gpio[line].output && !GPIO_IS_VALID_OUTPUT_GPIO(pin)) ||
            gpio_config(&configuration) != ESP_OK ||
            (board_gpio[line].output && gpio_set_level(pin, 0) != ESP_OK)) {
            for (uint32_t initialized = 0; initialized <= line; ++initialized)
                gpio_reset_pin(board_gpio[initialized].pin);
            free(gpio);
            return NULL;
        }
    }
    gpio->lines = board_gpio_lines;
    /* Reserve ADC1 once during runtime initialization, only if the graph has
     * eligible inputs. ADC2 is deliberately excluded because Wi-Fi owns it. */
    for (uint32_t line = 0; line < gpio->lines; ++line) {
        adc_unit_t unit;
        adc_channel_t channel;
        if (!board_gpio[line].output &&
            adc_oneshot_io_to_channel(board_gpio[line].pin, &unit, &channel) == ESP_OK &&
            unit == ADC_UNIT_1) {
            adc_oneshot_unit_init_cfg_t config = {.unit_id = ADC_UNIT_1};
            if (adc_oneshot_new_unit(&config, &gpio->adc) != ESP_OK) {
                micros_platform_gpio_destroy(gpio);
                return NULL;
            }
            break;
        }
    }
    return gpio;
}
void micros_platform_gpio_destroy(micros_platform_gpio_t *gpio)
{
    if (gpio->adc) adc_oneshot_del_unit(gpio->adc);
    for (uint32_t line = 0; line < gpio->lines; ++line) {
        if (board_gpio[line].output)
            gpio_set_level(board_gpio[line].pin, 0);
        gpio_reset_pin(board_gpio[line].pin);
    }
    free(gpio);
}
micros_result_t micros_platform_gpio_read(micros_platform_gpio_t *gpio, uint32_t line,
                                          uint32_t *level)
{
    if (!level || line >= gpio->lines)
        return MICROS_ERROR_INVALID_ARGUMENT;
    if (gpio->analog_lines & (UINT32_C(1) << line))
        return MICROS_ERROR_UNSUPPORTED;
    *level = (uint32_t)gpio_get_level(board_gpio[line].pin);
    return MICROS_OK;
}
micros_result_t micros_platform_gpio_write(micros_platform_gpio_t *gpio, uint32_t line,
                                           uint32_t level)
{
    if (line >= gpio->lines || level > 1)
        return MICROS_ERROR_INVALID_ARGUMENT;
    if (!board_gpio[line].output)
        return MICROS_ERROR_UNSUPPORTED;
    return gpio_set_level(board_gpio[line].pin, level) == ESP_OK ? MICROS_OK
                                                               : MICROS_ERROR_SERVICE;
}
micros_result_t micros_platform_gpio_read_analog(micros_platform_gpio_t *gpio, uint32_t line,
                                                uint32_t *raw)
{
    if (!raw || line >= gpio->lines) return MICROS_ERROR_INVALID_ARGUMENT;
    adc_unit_t unit;
    adc_channel_t channel;
    if (board_gpio[line].output || !gpio->adc ||
        adc_oneshot_io_to_channel(board_gpio[line].pin, &unit, &channel) != ESP_OK ||
        unit != ADC_UNIT_1) return MICROS_ERROR_UNSUPPORTED;
    if (!(gpio->analog_lines & (UINT32_C(1) << line))) {
        adc_oneshot_chan_cfg_t config = {.atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_12};
        if (adc_oneshot_config_channel(gpio->adc, channel, &config) != ESP_OK)
            return MICROS_ERROR_SERVICE;
        gpio->analog_lines |= UINT32_C(1) << line;
    }
    int value;
    esp_err_t result = adc_oneshot_read(gpio->adc, channel, &value);
    if (result != ESP_OK) return result == ESP_ERR_TIMEOUT ? MICROS_ERROR_BUSY : MICROS_ERROR_SERVICE;
    *raw = (uint32_t)value;
    return MICROS_OK;
}
void micros_platform_gpio_release(micros_platform_gpio_t *gpio, uint32_t line)
{
    if (line >= gpio->lines || !(gpio->analog_lines & (UINT32_C(1) << line))) return;
    /* ADC configuration disables the digital input; restore it for the next owner. */
    gpio_config_t config = {.pin_bit_mask = UINT64_C(1) << board_gpio[line].pin,
                           .mode = GPIO_MODE_INPUT, .intr_type = GPIO_INTR_DISABLE};
    gpio_config(&config);
    gpio->analog_lines &= ~(UINT32_C(1) << line);
}
micros_platform_sync_t *micros_platform_sync_create(void)
{
    micros_platform_sync_t *sync = calloc(1, sizeof(*sync));
    if (!sync)
        return NULL;
    sync->mutex = xSemaphoreCreateMutexStatic(&sync->mutex_storage);
    return sync;
}
void micros_platform_sync_destroy(micros_platform_sync_t *sync)
{
    vSemaphoreDelete(sync->mutex);
    free(sync);
}
void micros_platform_lock(micros_platform_sync_t *sync)
{
    xSemaphoreTake(sync->mutex, portMAX_DELAY);
}
void micros_platform_unlock(micros_platform_sync_t *sync)
{
    xSemaphoreGive(sync->mutex);
}
void micros_platform_notify(micros_platform_sync_t *sync)
{
    for (unsigned slot = 0; slot < MICROS_BOARD_WAITERS; ++slot)
        if (sync->waiters[slot])
            xTaskNotifyGive(sync->waiters[slot]);
}
uint64_t micros_platform_now_us(void)
{
    return (uint64_t)esp_timer_get_time();
}
void micros_platform_wait(micros_platform_sync_t *sync, uint64_t deadline_us)
{
    uint64_t now_us = micros_platform_now_us();
    if (deadline_us <= now_us)
        return;
    unsigned slot = 0;
    while (slot < MICROS_BOARD_WAITERS && sync->waiters[slot])
        ++slot;
    configASSERT(slot < MICROS_BOARD_WAITERS);
    /* Registration and pending-notification clearing happen under the mutex:
     * a broadcaster cannot be lost between unlocking and entering the wait. */
    ulTaskNotifyTake(pdTRUE, 0);
    sync->waiters[slot] = xTaskGetCurrentTaskHandle();
    uint64_t delay_ms =
        (deadline_us - now_us + 999) / 1000; /* Ceil microseconds to milliseconds. */
    TickType_t ticks = pdMS_TO_TICKS(delay_ms);
    if (!ticks)
        ticks = 1; /* A positive condition wait must yield at least one RTOS tick. */
    micros_platform_unlock(sync);
    ulTaskNotifyTake(pdTRUE, ticks);
    micros_platform_lock(sync);
    sync->waiters[slot] = NULL;
}
size_t micros_platform_stack_bytes(size_t bytes)
{
    return (bytes + sizeof(StackType_t) - 1) / sizeof(StackType_t) * sizeof(StackType_t);
}
size_t micros_platform_metadata_bytes(uint32_t lines)
{
    (void)lines;
    return sizeof(micros_platform_sync_t) + sizeof(micros_platform_gpio_t);
}
size_t micros_platform_task_metadata_bytes(void)
{
    return sizeof(micros_platform_task_t);
}
void *micros_platform_arena_allocate(size_t alignment, size_t bytes, uint32_t placement)
{
    return heap_caps_aligned_alloc(alignment, bytes, (placement == 1 ? MALLOC_CAP_SPIRAM : MALLOC_CAP_INTERNAL) | MALLOC_CAP_8BIT);
}
static void task_entry(void *argument)
{
    micros_platform_task_t *task = argument;
    task->entry(task->argument);
    xSemaphoreGive(task->done);
    vTaskSuspend(NULL); /* Join waits for this parked state before deleting static storage. */
    abort();
}
static micros_platform_task_t *create_task(void *(*entry)(void *), void *argument, size_t bytes,
                                           unsigned priority)
{
    micros_platform_task_t *task = calloc(1, sizeof(*task));
    if (!task)
        return NULL;
    task->stack = heap_caps_malloc(bytes, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (!task->stack) {
        free(task);
        return NULL;
    }
    task->entry = entry;
    task->argument = argument;
    task->done = xSemaphoreCreateBinaryStatic(&task->done_storage);
    /* ESP-IDF's task creation API uses stack bytes, unlike upstream FreeRTOS ports. */
    task->task =
        xTaskCreateStaticPinnedToCore(task_entry, "micros", bytes, task, priority, task->stack,
                                      &task->task_storage, MICROS_BOARD_RUNTIME_CORE);
    if (!task->task) {
        vSemaphoreDelete(task->done);
        free(task->stack);
        free(task);
        return NULL;
    }
    return task;
}
micros_platform_task_t *micros_platform_task_create(void *(*entry)(void *), void *argument,
                                                    size_t bytes)
{
    return create_task(entry, argument, bytes, MICROS_BOARD_WORKER_PRIORITY);
}
micros_platform_task_t *micros_platform_supervisor_create(void *(*entry)(void *), void *argument,
                                                          size_t bytes)
{
    return create_task(entry, argument, bytes, MICROS_BOARD_SUPERVISOR_PRIORITY);
}
size_t micros_platform_stack_free(micros_platform_task_t *task)
{
    return uxTaskGetStackHighWaterMark(task->task);
}
void micros_platform_task_join(micros_platform_task_t *task)
{
    xSemaphoreTake(task->done, portMAX_DELAY);
    while (eTaskGetState(task->task) != eSuspended)
        vTaskDelay(1);
    vTaskDelete(task->task);
    vSemaphoreDelete(task->done);
    free(task->stack);
    free(task);
}
void micros_platform_debug_to_stderr(void)
{
} /* Device diagnostics share the framed serial console. */
micros_result_t micros_platform_debug(const uint8_t *message, uint32_t bytes)
{
    micros_management_log(message, bytes);
    return fwrite(message, 1, bytes, stdout) == bytes ? MICROS_OK : MICROS_ERROR_SERVICE;
}
static micros_result_t open_image_bytes(unsigned bank, uint8_t *bytes, size_t size,
                                        micros_platform_image_t **output,
                                        const micros_service_descriptor_t **descriptor,
                                        size_t *payload_bytes)
{
    micros_image_t layout;
    if (micros_image_validate(bytes, size, MICROS_TARGET_ESP32_XTENSA, &layout)) {
        free(bytes);
        return MICROS_ERROR_INVALID_ARGUMENT;
    }
    unsigned slot = 0;
    while (slot < MICROS_BOARD_IMAGE_SLOTS &&
           (layout.code_base != (uint32_t)(uintptr_t)code_slots[slot] ||
            layout.data_base != (uint32_t)(uintptr_t)data_slots[slot]))
        ++slot;
    if (slot == MICROS_BOARD_IMAGE_SLOTS || layout.code_bytes > MICROS_BOARD_CODE_BYTES ||
        layout.data_bytes + layout.bss_bytes > MICROS_BOARD_DATA_BYTES) {
        free(bytes);
        return MICROS_ERROR_CAPACITY;
    }
    if (slot_claimed[slot]) {
        free(bytes);
        return MICROS_ERROR_BUSY;
    }
    micros_platform_image_t *image = malloc(sizeof(*image));
    if (!image) {
        free(bytes);
        return MICROS_ERROR_CAPACITY;
    }
    if (micros_board_validate_bytes(bytes, size, slot)) {
        free(bytes);
        free(image);
        return MICROS_ERROR_INVALID_ARGUMENT;
    }
#if CONFIG_MICROS_SERVICE_FLASH
    const void *code, *rodata;
    size_t payload_offset = MICROS_STORAGE_SECTOR_BYTES + slot * MICROS_STORAGE_IMAGE_BYTES + MICROS_IMAGE_HEADER_BYTES;
    if (!micros_storage_map_bank(bank, &code, &rodata)) {
        free(bytes);
        free(image);
        return MICROS_ERROR_CAPACITY;
    }
    if ((uintptr_t)code + payload_offset != layout.code_base ||
        (uintptr_t)rodata + payload_offset != layout.rodata_base) {
        micros_storage_unmap_bank();
        free(bytes);
        free(image);
        return MICROS_ERROR_INVALID_ARGUMENT;
    }
#else
    (void)bank;
    for (size_t offset = 0; offset < layout.code_bytes; offset += sizeof(uint32_t)) {
        uint32_t word;
        memcpy(&word, bytes + MICROS_IMAGE_HEADER_BYTES + offset, sizeof(word));
        ((volatile uint32_t *)code_slots[slot])[offset / sizeof(uint32_t)] = word;
    }
#endif
    memcpy(data_slots[slot], bytes + MICROS_IMAGE_HEADER_BYTES + layout.code_bytes,
           layout.data_bytes);
    memset(data_slots[slot] + layout.data_bytes, 0, layout.bss_bytes);
    free(bytes);
    __asm__ volatile("memw\n isync" ::: "memory");
    const micros_service_descriptor_t *native =
        (const void *)(data_slots[slot] + layout.descriptor_offset);
    const char *error = micros_descriptor_validate(native, MICROS_TARGET_ESP32_XTENSA);
    micros_service_hook_t hooks[] = {native->init, native->start, native->step, native->stop};
    for (unsigned hook = 0; hook < 4 && !error; ++hook) {
        uintptr_t address = (uintptr_t)hooks[hook];
        if (address < layout.code_base || address >= layout.code_base + layout.code_bytes - layout.rodata_bytes)
            error = "hook range";
    }
    if (error) {
#if CONFIG_MICROS_SERVICE_FLASH
        micros_storage_unmap_bank();
#endif
        free(image);
        return MICROS_ERROR_INVALID_ARGUMENT;
    }
    image->slot = slot;
    slot_claimed[slot] = 1;
    *output = image;
    *descriptor = native;
    *payload_bytes = layout.code_bytes + layout.data_bytes;
    return MICROS_OK;
}
micros_result_t micros_platform_image_open(const char *path, micros_platform_image_t **output,
                                           const micros_service_descriptor_t **descriptor,
                                           size_t *payload_bytes)
{
    unsigned bank, slot;
    if (sscanf(path, "/services/b%u-s%u.mimg", &bank, &slot) != 2)
        return MICROS_ERROR_INVALID_ARGUMENT;
    size_t bytes;
    uint8_t *image = micros_storage_read_image(bank, slot, &bytes);
    return image ? open_image_bytes(bank, image, bytes, output, descriptor, payload_bytes)
                 : MICROS_ERROR_INVALID_ARGUMENT;
}
void micros_platform_image_close(micros_platform_image_t *image)
{
    /* The manager has joined all execution before making this slot reusable. */
    slot_claimed[image->slot] = 0;
#if CONFIG_MICROS_SERVICE_FLASH
    micros_storage_unmap_bank();
#endif
    memset(data_slots[image->slot], 0, MICROS_BOARD_DATA_BYTES);
    free(image);
}
int micros_board_validate_image(const char *path, unsigned expected_slot)
{
    micros_platform_image_t *image;
    const micros_service_descriptor_t *descriptor;
    size_t bytes;
    micros_result_t result = micros_platform_image_open(path, &image, &descriptor, &bytes);
    if (result)
        return result;
    result = image->slot == expected_slot ? MICROS_OK : MICROS_ERROR_INVALID_ARGUMENT;
    micros_platform_image_close(image);
    return result;
}

int micros_board_validate_bytes(const void *bytes, size_t size, unsigned expected_slot)
{
    micros_image_t layout;
    if (expected_slot >= MICROS_BOARD_IMAGE_SLOTS ||
        micros_image_validate(bytes, size, MICROS_TARGET_ESP32_XTENSA, &layout))
        return MICROS_ERROR_INVALID_ARGUMENT;
    if (layout.code_base != (uint32_t)(uintptr_t)code_slots[expected_slot] ||
        layout.data_base != (uint32_t)(uintptr_t)data_slots[expected_slot] ||
        layout.code_bytes > MICROS_BOARD_CODE_BYTES ||
        layout.data_bytes + layout.bss_bytes > MICROS_BOARD_DATA_BYTES)
        return MICROS_ERROR_CAPACITY;
#if CONFIG_MICROS_SERVICE_FLASH
    if (layout.rodata_base != (uint32_t)(uintptr_t)rodata_slots[expected_slot])
        return MICROS_ERROR_INVALID_ARGUMENT;
#else
    if (layout.rodata_base) return MICROS_ERROR_INVALID_ARGUMENT;
#endif
    /* Validate the descriptor in staging RAM without overwriting an executable
     * slot. Target pointers are checked as addresses and are never called here. */
    micros_service_descriptor_t descriptor;
    memcpy(&descriptor,
           (const uint8_t *)bytes + MICROS_IMAGE_HEADER_BYTES + layout.code_bytes +
               layout.descriptor_offset,
           sizeof(descriptor));
    if (micros_descriptor_validate(&descriptor, MICROS_TARGET_ESP32_XTENSA))
        return MICROS_ERROR_INVALID_ARGUMENT;
    micros_service_hook_t hooks[] = {descriptor.init, descriptor.start, descriptor.step,
                                     descriptor.stop};
    for (unsigned index = 0; index < sizeof(hooks) / sizeof(hooks[0]); ++index) {
        uintptr_t address = (uintptr_t)hooks[index];
        if (address < layout.code_base || address >= layout.code_base + layout.code_bytes - layout.rodata_bytes)
            return MICROS_ERROR_INVALID_ARGUMENT;
    }
    return MICROS_OK;
}

void micros_platform_arena_free(void *arena) { free(arena); }

#include <micros/platform.h>
#include <micros/capabilities.h>
#include <micros/controller.h>
#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp_heap_caps.h"
#include "esp_system.h"
#include "esp_random.h"
#include "esp_app_desc.h"
#include "esp_mac.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
void micros_controller_initialize(uint64_t *boot_identity)
{
    esp_fill_random(boot_identity, sizeof(*boot_identity));
    vTaskPrioritySet(NULL, MICROS_BOARD_SUPERVISOR_PRIORITY);
    uart_config_t uart = {.baud_rate = 115200, .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE, .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE, .source_clk = UART_SCLK_DEFAULT};
    ESP_ERROR_CHECK(uart_param_config(UART_NUM_0, &uart));
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0, 32u * 1024u, 0, 0, NULL, 0));
}
void micros_controller_reset(void) { esp_restart(); }
unsigned micros_controller_reset_reason(void) { return esp_reset_reason(); }
size_t micros_controller_heap_free(void) { return esp_get_free_heap_size(); }
int micros_controller_gpio_level(int pin) { return gpio_get_level(pin); }
int micros_controller_recovery_pressed(int pin)
{
    gpio_config_t input = {.pin_bit_mask = UINT64_C(1) << pin, .mode = GPIO_MODE_INPUT,
                           .intr_type = GPIO_INTR_DISABLE};
    ESP_ERROR_CHECK(gpio_config(&input));
    return gpio_get_level(pin) == 0;
}
const uint8_t *micros_controller_base_hash(void)
{
    static uint8_t hash[32];
    const volatile uint8_t *source = esp_app_get_description()->app_elf_sha256;
    for (unsigned i = 0; i < sizeof(hash); ++i) hash[i] = source[i];
    return hash;
}
void micros_controller_identity(uint8_t identity[6])
{ ESP_ERROR_CHECK(esp_read_mac(identity, ESP_MAC_WIFI_STA)); }
void *micros_controller_transfer_allocate(size_t bytes)
{ return heap_caps_malloc(bytes, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT); }
void micros_controller_yield(void) { vTaskDelay(1); }

void micros_controller_bootloader(void) {}
