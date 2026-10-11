/* Supplement the Arduino bootloader-preserving linker script. */
ASSERT(__etext + SIZEOF(.data) <= __text_start__ + 0x14000, "SAMD21 base overlaps activation/storage region")
ASSERT(__bss_end__ + 2048 <= 0x20008000, "SAMD21 static RAM overlaps reserved interrupt stack")
