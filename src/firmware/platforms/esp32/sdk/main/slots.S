#include "board_profile.h"
.section .iram1,"ax",@progbits
.balign MICROS_BOARD_SLOT_ALIGNMENT
.global micros_code_slot0
.type micros_code_slot0,@object
micros_code_slot0:
.space MICROS_BOARD_CODE_BYTES
.size micros_code_slot0, .-micros_code_slot0
.global micros_code_slot1
.type micros_code_slot1,@object
micros_code_slot1:
.space MICROS_BOARD_CODE_BYTES
.size micros_code_slot1, .-micros_code_slot1
.global micros_code_slot2
.type micros_code_slot2,@object
micros_code_slot2:
.space MICROS_BOARD_CODE_BYTES
.size micros_code_slot2, .-micros_code_slot2
.global micros_code_slot3
.type micros_code_slot3,@object
micros_code_slot3:
.space MICROS_BOARD_CODE_BYTES
.size micros_code_slot3, .-micros_code_slot3
