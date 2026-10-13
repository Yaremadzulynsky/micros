idf_component_register(SRCS "main.c" "slots.S" "../../../kernel/src/loader/image.c" "../../../kernel/src/loader/elf.c"
    INCLUDE_DIRS "../../../abi/include" "../../../kernel/src/loader"
    REQUIRES esp_driver_uart esp_timer esp_system freertos)
target_compile_options(${COMPONENT_LIB} PRIVATE -std=gnu17 -Wall -Wextra -Werror)
