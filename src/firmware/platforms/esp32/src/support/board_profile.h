#ifndef MICROS_BOARD_PROFILE_H
#define MICROS_BOARD_PROFILE_H
#include "micros_board.h" /* Generated from the application's [board] definition. */
/* Four fixed virtual slots. Code/constants map flash by default; writable
 * reservations are configurable independently of arenas and task stacks. */
#define MICROS_BOARD_IMAGE_SLOTS 4
#include "sdkconfig.h"
#if CONFIG_MICROS_SERVICE_FLASH
#define MICROS_BOARD_CODE_BYTES 12288
#else
#define MICROS_BOARD_CODE_BYTES 8192
#endif
#define MICROS_BOARD_DATA_BYTES CONFIG_MICROS_SERVICE_DATA_BYTES
#define MICROS_BOARD_SLOT_ALIGNMENT 16
#define MICROS_BOARD_IMAGE_BYTES (64 + MICROS_BOARD_CODE_BYTES + MICROS_BOARD_DATA_BYTES)
/* Four workers, the deadline supervisor, and one management controller may wait. */
#define MICROS_BOARD_WAITERS 6
#define MICROS_BOARD_WORKER_PRIORITY 5
#define MICROS_BOARD_SUPERVISOR_PRIORITY 6
#define MICROS_BOARD_RUNTIME_CORE 1
#endif
