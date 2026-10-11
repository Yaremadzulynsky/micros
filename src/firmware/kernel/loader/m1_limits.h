#ifndef MICROS_M1_LIMITS_H
#define MICROS_M1_LIMITS_H

/* M1 policy, not hardware maxima or stable ABI requirements. Keep this header
 * preprocessor-only: slots.S also uses the executable-slot reservation. */

/* Fixed-slot feasibility budgets; intentionally larger than the hello service.
 * These reserve bounded internal RAM without implementing dynamic placement. */
#define MICROS_M1_CODE_SLOT_BYTES (16 * 1024)
#define MICROS_M1_DATA_SLOT_BYTES (8 * 1024)

/* A 4 KiB arena/stack is the initial demo budget, not a general sizing rule.
 * 16-byte slot alignment covers the prototype's admitted arena alignments. */
#define MICROS_M1_ARENA_BYTES (4 * 1024)
#define MICROS_M1_STACK_BYTES (4 * 1024)
#define MICROS_M1_SLOT_ALIGNMENT 16

/* Shared descriptor admission ceiling; the MCU harness applies its stricter
 * 4 KiB actual stack reservation after this cross-platform check. */
#define MICROS_M1_MAX_STACK_BYTES (16 * 1024)

/* Three steps exercise retained state; two cycles demonstrate clean reload. */
#define MICROS_M1_STEP_COUNT 3
#define MICROS_M1_CYCLE_COUNT 2

/* M0's provisional failure-detection thresholds, not real-time guarantees.
 * Lifecycle hooks get 1 s; a step gets 10 ms; the task yields 1 ms per step. */
#define MICROS_M1_LIFECYCLE_TIMEOUT_MS 1000
#define MICROS_M1_STEP_TIMEOUT_MS 10
#define MICROS_M1_STEP_DELAY_MS 1

/* Pin service and supervisor to core 1; the supervisor's higher priority lets
 * it enforce deadlines even when the priority-5 service task spins. */
#define MICROS_M1_SERVICE_CORE 1
#define MICROS_M1_SERVICE_PRIORITY 5
#define MICROS_M1_SUPERVISOR_PRIORITY 6

/* 115200 was the reliable baud in M1 hardware testing. The 32 KiB RX buffer
 * can hold the entire 64-byte-header + 24 KiB-slot payload during a transfer. */
#define MICROS_M1_UART_BAUD 115200
#define MICROS_M1_UART_RX_BYTES (32 * 1024)

/* Ten seconds allows margin for a maximum-size transfer at 115200 baud.
 * Polling in 100 ms slices keeps checking the overall transfer deadline. */
#define MICROS_M1_TRANSFER_TIMEOUT_MS 10000
#define MICROS_M1_TRANSFER_POLL_MS 100

/* Only INFO, RUN, or LOAD plus a decimal byte count are accepted. 80 bytes is
 * a bounded command buffer with ample margin; larger input is not supported. */
#define MICROS_M1_COMMAND_BYTES 80

/* Unit conversions used by the platform clocks; these are not timing policy. */
#define MICROS_US_PER_MS 1000
#define MICROS_US_PER_SECOND 1000000
#define MICROS_NS_PER_US 1000

#endif
