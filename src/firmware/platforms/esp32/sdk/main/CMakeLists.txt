get_filename_component(MICROS_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../../../../.." ABSOLUTE)
set(MICROS_BOARD_GENERATED "${CMAKE_BINARY_DIR}/generated")
# IDF first scans dependencies without project cache/configuration variables.
if(NOT CMAKE_BUILD_EARLY_EXPANSION)
    if(NOT MICROS_BOARD_FILE)
        file(GLOB MICROS_BOARD_FILES "${MICROS_ROOT}/config/boards/*.toml")
        list(LENGTH MICROS_BOARD_FILES MICROS_BOARD_COUNT)
        if(NOT MICROS_BOARD_COUNT EQUAL 1)
            message(FATAL_ERROR "Select -D MICROS_BOARD_FILE=/absolute/path/board.toml")
        endif()
        list(GET MICROS_BOARD_FILES 0 MICROS_BOARD_FILE)
    endif()
    get_filename_component(MICROS_PARTITION_FILE "${CONFIG_PARTITION_TABLE_CUSTOM_FILENAME}"
        ABSOLUTE BASE_DIR "${MICROS_ROOT}/src/firmware/platforms/esp32/sdk")
    set(board_ota_arg "")
    if(CONFIG_MICROS_BASE_OTA)
        set(board_ota_arg "--ota")
    endif()
    execute_process(COMMAND "${MICROS_ROOT}/build/python/bin/python"
        "${MICROS_ROOT}/src/micros_tooling/config/generate_board.py"
        --board "${MICROS_BOARD_FILE}" --output "${MICROS_BOARD_GENERATED}/micros_board.h"
        --flash-size "${CONFIG_ESPTOOLPY_FLASHSIZE}" --partitions "${MICROS_PARTITION_FILE}" ${board_ota_arg}
        RESULT_VARIABLE MICROS_BOARD_RESULT)
    if(NOT MICROS_BOARD_RESULT EQUAL 0)
        message(FATAL_ERROR "Board generation failed. Run ./micros setup and check ${MICROS_BOARD_FILE}.")
    endif()
    set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
        "${MICROS_BOARD_FILE}" "${MICROS_ROOT}/src/micros_tooling/config/resources.py"
        "${MICROS_ROOT}/src/micros_tooling/config/generate_board.py")

endif()

include("${MICROS_ROOT}/src/firmware/contracts/requirements.cmake")
set(service_slots "slots.S")
if(CONFIG_MICROS_SERVICE_FLASH)
    set(service_slots "")
endif()
set(management_sources "")
if(CONFIG_MICROS_REMOTE_ENABLED)
    set(management_sources
        "${MICROS_ROOT}/src/firmware/controller/support/wifi_credentials.c"
        "${MICROS_ROOT}/src/firmware/controller/support/auth.c"
        "${MICROS_ROOT}/src/firmware/platforms/esp32/src/support/management/relay.c")
endif()
idf_component_register(SRCS ${management_sources} "${MICROS_ROOT}/src/firmware/platforms/esp32/src/update.c"
    "main.c" "../../src/transport.c" "../../src/network.c" "${MICROS_ROOT}/src/firmware/controller/controller.c" ${service_slots} "../../src/platform.c" "../../src/telemetry.c" "${MICROS_ROOT}/src/firmware/controller/status.c" "${MICROS_ROOT}/src/firmware/controller/application.c" "${MICROS_ROOT}/src/firmware/controller/protocol/ipc_console.c" "../../src/storage.c"
    "../../../../kernel/deployment/activation.c" "../../../../kernel/hash/sha256.c" "${MICROS_ROOT}/src/firmware/controller/deployment.c"
    "../../../../kernel/runtime/runtime.c" "../../../../kernel/ipc/channel.c"
    "../../../../kernel/loader/image.c" "../../../../kernel/loader/elf.c"
    INCLUDE_DIRS "${MICROS_BOARD_GENERATED}" "../.." "${MICROS_ROOT}/src/firmware/controller/include" "../../src/support" "../../../../../sdk/abi/include" "../../../../contracts/include"
    "../../../../kernel/deployment" "../../../../kernel/hash" "../../../../kernel/runtime" "../../../../kernel/ipc" "../../../../kernel/loader"
    REQUIRES esp_adc esp_psram app_update esp_driver_uart esp_driver_gpio esp_timer esp_system esp_app_format freertos esp_partition mbedtls esp_https_server esp_http_client esp_wifi nvs_flash)
target_compile_options(${COMPONENT_LIB} PRIVATE -include "${MICROS_BOARD_GENERATED}/micros_board.h")
# Retain the fingerprint for host-side ELF verification even with section GC.
target_link_libraries(${COMPONENT_LIB} INTERFACE
    "-Wl,--undefined=micros_board_config_sha256" "-Wl,--undefined=micros_board_gpio_count" "-Wl,--undefined=micros_board_dynamic_bindings" "-Wl,--undefined=micros_board_flash_mb")
target_compile_options(${COMPONENT_LIB} PRIVATE -std=gnu17 -Wall -Wextra -Werror)

if(CONFIG_MICROS_REMOTE_ENABLED)
    if(NOT MICROS_CREDENTIALS_DIR)
        set(MICROS_CREDENTIALS_DIR "${MICROS_ROOT}/build/private")
    endif()
    target_add_binary_data(${COMPONENT_LIB} "${MICROS_CREDENTIALS_DIR}/servercert.pem" TEXT)
    target_add_binary_data(${COMPONENT_LIB} "${MICROS_CREDENTIALS_DIR}/prvtkey.pem" TEXT)
endif()
if(CONFIG_MICROS_RELAY_ENABLED)
    if(NOT MICROS_RELAY_CREDENTIALS_DIR)
        message(FATAL_ERROR "Relay requires private enrollment credentials")
    endif()
    target_add_binary_data(${COMPONENT_LIB} "${MICROS_RELAY_CREDENTIALS_DIR}/relay-ca.pem" TEXT)
endif()

if(CONFIG_MICROS_SERVICE_FLASH)
    target_link_libraries(${COMPONENT_LIB} INTERFACE "-T${CMAKE_CURRENT_LIST_DIR}/flash_slots.ld")
    set_property(TARGET ${COMPONENT_LIB} APPEND PROPERTY INTERFACE_LINK_DEPENDS "${CMAKE_CURRENT_LIST_DIR}/flash_slots.ld")
endif()
target_link_libraries(${COMPONENT_LIB} INTERFACE
    "-Wl,--defsym=micros_service_data_capacity=${CONFIG_MICROS_SERVICE_DATA_BYTES}")

if(CONFIG_MICROS_BASE_OTA)
    target_link_libraries(${COMPONENT_LIB} INTERFACE "-Wl,--undefined=micros_base_ota_version")
endif()

target_link_libraries(${COMPONENT_LIB} INTERFACE "-u micros_arena_placement_version")
