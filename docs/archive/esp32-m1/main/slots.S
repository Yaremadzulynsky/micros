/* Stable within this base image. Services link against exported slot addresses. */
#include "m1_limits.h"
.section .iram1,"ax",@progbits
.balign MICROS_M1_SLOT_ALIGNMENT
.global micros_code_slot
.type micros_code_slot,@object
micros_code_slot:
.space MICROS_M1_CODE_SLOT_BYTES
.size micros_code_slot, .-micros_code_slot
