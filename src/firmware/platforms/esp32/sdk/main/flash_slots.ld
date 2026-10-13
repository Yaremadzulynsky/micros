/* ESP-IDF v5.5.2 maps the first available whole MMU pages after the base.
 * The loader verifies BOTH returned addresses before exposing any service. */
micros_service_flash = 1;
micros_service_code_capacity = 12288;
micros_code_slot0 = ALIGN(_instruction_reserved_end, 0x10000) + 0x1040;
micros_code_slot1 = micros_code_slot0 + 0x4000;
micros_code_slot2 = micros_code_slot0 + 0x8000;
micros_code_slot3 = micros_code_slot0 + 0xc000;
micros_rodata_slot0 = ALIGN(_rodata_reserved_end, 0x10000) + 0x1040;
micros_rodata_slot1 = micros_rodata_slot0 + 0x4000;
micros_rodata_slot2 = micros_rodata_slot0 + 0x8000;
micros_rodata_slot3 = micros_rodata_slot0 + 0xc000;
