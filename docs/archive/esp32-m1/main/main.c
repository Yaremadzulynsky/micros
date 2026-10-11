#include "driver/uart.h"
#include "esp_attr.h"
#include "esp_heap_caps.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "image.h"
#include "m1_limits.h"
#include "unsupported_resources.h"
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Private task-notification opcodes, not wire or public ABI values.
 * Zero means no notification; 1–4 select lifecycle hooks and 5 parks the task. */
enum {
    SERVICE_COMMAND_INIT = 1,
    SERVICE_COMMAND_START = 2,
    SERVICE_COMMAND_STEP = 3,
    SERVICE_COMMAND_STOP = 4,
    SERVICE_COMMAND_PARK = 5
};
#define LOAD_COMMAND_PREFIX "LOAD "

extern uint32_t micros_code_slot[];
__attribute__((
    aligned(MICROS_M1_SLOT_ALIGNMENT))) uint8_t micros_data_slot[MICROS_M1_DATA_SLOT_BYTES];
static uint8_t image_staging_buffer[MICROS_IMAGE_HEADER_BYTES + MICROS_M1_CODE_SLOT_BYTES +
                                    MICROS_M1_DATA_SLOT_BYTES];
static uint8_t service_arena[MICROS_M1_ARENA_BYTES]
    __attribute__((aligned(MICROS_M1_SLOT_ALIGNMENT)));
static StackType_t service_stack[MICROS_M1_STACK_BYTES / sizeof(StackType_t)];
static StaticTask_t service_task_control_block;
static size_t staged_image_bytes;
static TaskHandle_t supervisor_task;
static volatile micros_result_t hook_result;
static micros_service_args_t service_args;
static const micros_service_descriptor_t *service_descriptor;
/**
 * @brief ESP32-owned instance state passed opaquely through service API calls.
 *
 * Records accepted diagnostic write attempts for the loader's run report.
 * The service accesses this state only through the kernel callback table.
 */
struct micros_context {
    /** UART write attempts that passed argument and capacity checks. */
    unsigned diagnostic_write_count;
};
static micros_context_t service_context;
static micros_result_t debug_write(micros_context_t *context, const uint8_t *message,
                                   uint32_t message_bytes)
{
    if (message_bytes > MICROS_DEBUG_MAX_BYTES)
        return MICROS_ERROR_CAPACITY;
    if (!message && message_bytes)
        return MICROS_ERROR_INVALID_ARGUMENT;
    ++context->diagnostic_write_count;
    return uart_write_bytes(UART_NUM_0, message, message_bytes) == (int)message_bytes
               ? MICROS_OK
               : MICROS_ERROR_SERVICE;
}
static uint64_t monotonic_us(micros_context_t *context)
{
    (void)context;
    return (uint64_t)esp_timer_get_time();
}
static const micros_api_t service_api = {
    .struct_bytes = sizeof(micros_api_t), .abi_major = MICROS_ABI_MAJOR,
    .abi_revision = MICROS_ABI_REVISION, .debug_write = debug_write,
    .monotonic_us = monotonic_us, .timer_open = micros_unsupported_timer_open,
    .timer_close = micros_unsupported_resource_close, .gpio_open = micros_unsupported_gpio_open,
    .gpio_read = micros_unsupported_gpio_read, .gpio_write = micros_unsupported_gpio_write,
    .gpio_close = micros_unsupported_resource_close,
    ._ipc = NULL
};
/* The supervisor dispatches one hook at a time and waits for its completion. */
static void service_task(void *unused)
{
    (void)unused;
    for (;;) {
        uint32_t command = 0;
        xTaskNotifyWait(0, UINT32_MAX, &command, portMAX_DELAY);
        if (command == SERVICE_COMMAND_PARK) {
            vTaskSuspend(NULL);
            continue;
        }
        micros_service_hook_t lifecycle_hook =
            command == SERVICE_COMMAND_INIT    ? service_descriptor->init
            : command == SERVICE_COMMAND_START ? service_descriptor->start
            : command == SERVICE_COMMAND_STEP  ? service_descriptor->step
                                               : service_descriptor->stop;
        hook_result = lifecycle_hook(&service_args);
        xTaskNotifyGive(supervisor_task);
    }
}
static micros_result_t call_hook(TaskHandle_t service_task_handle, uint32_t command,
                                 unsigned timeout_ms)
{
    int64_t hook_started_us = esp_timer_get_time();
    xTaskNotify(service_task_handle, command, eSetValueWithOverwrite);
    if (!ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(timeout_ms))) {
        printf("FATAL hook timeout command=%" PRIu32 " reboot required\n", command);
        fflush(stdout);
        esp_restart();
    }
    if (esp_timer_get_time() - hook_started_us > (int64_t)timeout_ms * MICROS_US_PER_MS)
        return MICROS_ERROR_SERVICE;
    return hook_result;
}
/* No service task is running while these fixed slots are validated and filled. */
static const char *load_image(micros_image_t *image_header)
{
    const char *error = micros_image_validate(image_staging_buffer, staged_image_bytes,
                                              MICROS_TARGET_ESP32_XTENSA, image_header);
    if (error)
        return error;
    if (image_header->code_base != (uint32_t)(uintptr_t)micros_code_slot ||
        image_header->data_base != (uint32_t)(uintptr_t)micros_data_slot)
        return "slot address mismatch";
    if (image_header->code_bytes > MICROS_M1_CODE_SLOT_BYTES ||
        image_header->data_bytes > sizeof(micros_data_slot) ||
        image_header->bss_bytes > sizeof(micros_data_slot) - image_header->data_bytes)
        return "slot capacity";
    /* Instruction RAM permits only aligned 32-bit data accesses. */
    for (uint32_t byte_offset = 0; byte_offset < image_header->code_bytes;
         byte_offset += sizeof(uint32_t)) {
        uint32_t instruction_word;
        memcpy(&instruction_word, image_staging_buffer + MICROS_IMAGE_HEADER_BYTES + byte_offset,
               sizeof(instruction_word));
        micros_code_slot[byte_offset / sizeof(instruction_word)] = instruction_word;
    }
    memcpy(micros_data_slot,
           image_staging_buffer + MICROS_IMAGE_HEADER_BYTES + image_header->code_bytes,
           image_header->data_bytes);
    memset(micros_data_slot + image_header->data_bytes, 0, image_header->bss_bytes);
    __asm__ volatile("memw\n\tisync" ::: "memory");
    service_descriptor =
        (const micros_service_descriptor_t *)(micros_data_slot + image_header->descriptor_offset);
    error = micros_descriptor_validate(service_descriptor, MICROS_TARGET_ESP32_XTENSA);
    if (error)
        return error;
    if (service_descriptor->stack_bytes > sizeof(service_stack))
        return "task stack capacity";
    micros_service_hook_t lifecycle_hooks[] = {service_descriptor->init, service_descriptor->start,
                                               service_descriptor->step, service_descriptor->stop};
    for (unsigned hook_index = 0; hook_index < sizeof(lifecycle_hooks) / sizeof(lifecycle_hooks[0]);
         ++hook_index) {
        uintptr_t hook_address = (uintptr_t)lifecycle_hooks[hook_index];
        if (hook_address < image_header->code_base ||
            hook_address >= image_header->code_base + image_header->code_bytes ||
            (hook_address & (MICROS_IMAGE_WORD_BYTES - 1)))
            return "hook address";
    }
    return NULL;
}
static void run_image(void)
{
    for (unsigned cycle = 1; cycle <= MICROS_M1_CYCLE_COUNT; ++cycle) {
        micros_image_t image;
        const char *error = load_image(&image);
        if (error) {
            printf("REJECT %s\n", error);
            return;
        }
        memset(service_arena, 0, sizeof(service_arena));
        service_context.diagnostic_write_count = 0;
        service_args =
            (micros_service_args_t){sizeof(service_args), service_descriptor->arena_bytes,
                                    &service_context, &service_api, service_arena, NULL, 0};
        TaskHandle_t service_task_handle = xTaskCreateStaticPinnedToCore(
            service_task, "service", sizeof(service_stack), NULL, MICROS_M1_SERVICE_PRIORITY,
            service_stack, &service_task_control_block, MICROS_M1_SERVICE_CORE);
        if (!service_task_handle) {
            printf("REJECT task allocation\n");
            return;
        }
        micros_result_t result =
            call_hook(service_task_handle, SERVICE_COMMAND_INIT, MICROS_M1_LIFECYCLE_TIMEOUT_MS);
        if (!result)
            result = call_hook(service_task_handle, SERVICE_COMMAND_START,
                               MICROS_M1_LIFECYCLE_TIMEOUT_MS);
        for (unsigned step = 0; step < MICROS_M1_STEP_COUNT && !result; ++step) {
            result =
                call_hook(service_task_handle, SERVICE_COMMAND_STEP, MICROS_M1_STEP_TIMEOUT_MS);
            vTaskDelay(pdMS_TO_TICKS(MICROS_M1_STEP_DELAY_MS));
        }
        micros_result_t stop_result =
            call_hook(service_task_handle, SERVICE_COMMAND_STOP, MICROS_M1_LIFECYCLE_TIMEOUT_MS);
        if (!result)
            result = stop_result;
        xTaskNotify(service_task_handle, SERVICE_COMMAND_PARK, eSetValueWithOverwrite);
        while (eTaskGetState(service_task_handle) != eSuspended)
            vTaskDelay(1); /* One scheduler tick lets the worker process PARK. */
        unsigned minimum_free_stack_bytes =
            (unsigned)uxTaskGetStackHighWaterMark(service_task_handle);
        vTaskDelete(service_task_handle); /* Suspended after returning from all service code. */
        printf("CYCLE %u result=%" PRId32 " code=%" PRIu32 " data=%" PRIu32 " bss=%" PRIu32
               " arena=%" PRIu32 " stack=%u stack_free_min=%u writes=%u\n",
               cycle, result, image.code_bytes, image.data_bytes, image.bss_bytes,
               service_descriptor->arena_bytes, (unsigned)sizeof(service_stack),
               minimum_free_stack_bytes, service_context.diagnostic_write_count);
        if (result)
            return;
    }
    printf("DONE\n");
}
/* Read the announced binary payload within one bounded transfer deadline. */
static int read_exact(uint8_t *destination, size_t requested_bytes)
{
    size_t received_bytes = 0;
    int64_t read_deadline_us =
        esp_timer_get_time() + (int64_t)MICROS_M1_TRANSFER_TIMEOUT_MS * MICROS_US_PER_MS;
    while (received_bytes < requested_bytes && esp_timer_get_time() < read_deadline_us) {
        int chunk_bytes = uart_read_bytes(UART_NUM_0, destination + received_bytes,
                                          requested_bytes - received_bytes,
                                          pdMS_TO_TICKS(MICROS_M1_TRANSFER_POLL_MS));
        if (chunk_bytes > 0)
            received_bytes += (size_t)chunk_bytes;
    }
    return received_bytes == requested_bytes;
}
void app_main(void)
{
    supervisor_task = xTaskGetCurrentTaskHandle();
    vTaskPrioritySet(NULL, MICROS_M1_SUPERVISOR_PRIORITY);
    const uart_config_t uart_config = {.baud_rate = MICROS_M1_UART_BAUD,
                                       .data_bits = UART_DATA_8_BITS,
                                       .parity = UART_PARITY_DISABLE,
                                       .stop_bits = UART_STOP_BITS_1,
                                       .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
                                       .source_clk = UART_SCLK_DEFAULT};
    ESP_ERROR_CHECK(uart_param_config(UART_NUM_0, &uart_config));
    /* UART0 is the existing console. Zero TX buffer means synchronous writes;
     * zero queue length/NULL queue and zero flags request no event queue/options. */
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0, MICROS_M1_UART_RX_BYTES, 0, 0, NULL, 0));
    printf("MICROS M1 ready\n");
    for (;;) {
        char command_line[MICROS_M1_COMMAND_BYTES];
        size_t command_length = 0;
        uint8_t received_character;
        do {
            if (uart_read_bytes(UART_NUM_0, &received_character, 1,
                                pdMS_TO_TICKS(MICROS_M1_LIFECYCLE_TIMEOUT_MS)) != 1)
                continue;
            if (received_character == '\n')
                break;
            if (received_character != '\r' && command_length < sizeof(command_line) - 1)
                command_line[command_length++] = (char)received_character;
        } while (1);
        command_line[command_length] = 0;
        if (!strcmp(command_line, "INFO")) {
            printf("INFO code=0x%08" PRIx32 " data=0x%08" PRIx32
                   " code_capacity=%u data_capacity=%u heap=%u staging=%u arena_reserved=%u "
                   "tcb=%u\n",
                   (uint32_t)(uintptr_t)micros_code_slot, (uint32_t)(uintptr_t)micros_data_slot,
                   MICROS_M1_CODE_SLOT_BYTES, MICROS_M1_DATA_SLOT_BYTES,
                   (unsigned)esp_get_free_heap_size(), (unsigned)sizeof(image_staging_buffer),
                   (unsigned)sizeof(service_arena), (unsigned)sizeof(service_task_control_block));
        } else if (!strncmp(command_line, LOAD_COMMAND_PREFIX, sizeof(LOAD_COMMAND_PREFIX) - 1)) {
            char *parse_end;
            unsigned long transfer_bytes = strtoul(command_line + sizeof(LOAD_COMMAND_PREFIX) - 1,
                                                   &parse_end, 10) /* decimal byte count */;
            staged_image_bytes = 0;
            if (*parse_end || transfer_bytes < MICROS_IMAGE_HEADER_BYTES ||
                transfer_bytes > sizeof(image_staging_buffer)) {
                printf("REJECT transfer length\n");
                continue;
            }
            printf("READY %lu\n", transfer_bytes);
            fflush(stdout);
            if (!read_exact(image_staging_buffer, transfer_bytes)) {
                printf("REJECT transfer timeout\n");
                continue;
            }
            staged_image_bytes = transfer_bytes;
            micros_image_t image_header;
            const char *error = load_image(&image_header);
            if (error) {
                staged_image_bytes = 0;
                printf("REJECT %s\n", error);
            } else
                printf("LOADED\n");
        } else if (!strcmp(command_line, "RUN"))
            run_image();
        else
            printf("REJECT command\n");
        fflush(stdout);
    }
}
