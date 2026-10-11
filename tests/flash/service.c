#include <micros/service.h>
/* Volatile index prevents folding away the read-only table and mutable state. */
static const unsigned char table[2048] = {1, 2, 3, 4};
static volatile unsigned index_value;
static unsigned mutable_value = 7;
static micros_result_t init(const micros_service_args_t *args)
{ (void)args; mutable_value += table[index_value & 2047]; return MICROS_OK; }
static micros_result_t start(const micros_service_args_t *args) { (void)args; return MICROS_OK; }
static micros_result_t step(const micros_service_args_t *args) { (void)args; ++index_value; return MICROS_OK; }
static micros_result_t stop(const micros_service_args_t *args) { (void)args; return MICROS_OK; }
__attribute__((used)) const micros_service_descriptor_t micros_descriptor = {
    .struct_bytes = sizeof(micros_service_descriptor_t), .target = MICROS_TARGET_ESP32_XTENSA,
    .abi_major = MICROS_ABI_MAJOR, .abi_revision = MICROS_ABI_REVISION,
    .arena_alignment = 1, .stack_bytes = 4096, .init = init, .start = start, .step = step, .stop = stop
};
const micros_service_descriptor_t *micros_service_query(void) { return &micros_descriptor; }
