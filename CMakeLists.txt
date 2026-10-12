cmake_minimum_required(VERSION 3.24)
# Record the SDK in compile_commands.json as well as using it during the build.
# Editor compiler probes do not necessarily inherit xcrun's SDK selection.
if(CMAKE_HOST_APPLE AND NOT CMAKE_OSX_SYSROOT)
    execute_process(COMMAND xcrun --sdk macosx --show-sdk-path
        OUTPUT_VARIABLE micros_macos_sdk OUTPUT_STRIP_TRAILING_WHITESPACE
        COMMAND_ERROR_IS_FATAL ANY)
    set(CMAKE_OSX_SYSROOT "${micros_macos_sdk}" CACHE PATH "macOS SDK" FORCE)
endif()
project(micros VERSION 1.0.0 LANGUAGES C CXX)
include_directories(src/firmware/platforms/posix src/firmware/platforms/posix/src/support src/firmware/controller/include src/firmware/contracts/include)
include(src/firmware/contracts/requirements.cmake)
# Module commands use the source tree, including on clean Linux build images.
set(ENV{PYTHONPATH} "${CMAKE_CURRENT_SOURCE_DIR}/src")
option(MICROS_ENABLE_SANITIZERS "Instrument the host kernel and BSP with ASan/UBSan" OFF)
set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED YES)
set(CMAKE_C_EXTENSIONS NO)
# Let editors use the same defines, include paths, and compiler flags as the build.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Public contract checks plus the M1 macOS loader harness. ESP32 has its own IDF entry.
add_library(micros_abi INTERFACE)
target_include_directories(micros_abi INTERFACE "${CMAKE_CURRENT_SOURCE_DIR}/src/sdk/abi/include")
target_compile_features(micros_abi INTERFACE c_std_17)

add_library(micros_abi_c_check OBJECT tools/checks/abi_compile.c)
target_link_libraries(micros_abi_c_check PRIVATE micros_abi)
set_target_properties(micros_abi_c_check PROPERTIES C_STANDARD 17 C_STANDARD_REQUIRED YES C_EXTENSIONS NO)

add_library(micros_abi_cpp_check OBJECT tools/checks/abi_compile.cpp)
target_link_libraries(micros_abi_cpp_check PRIVATE micros_abi)
set_target_properties(micros_abi_cpp_check PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED YES CXX_EXTENSIONS NO)

if(CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
    target_compile_options(micros_abi_c_check PRIVATE -Wall -Wextra -Werror -pedantic)
endif()
if(CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
    target_compile_options(micros_abi_cpp_check PRIVATE -Wall -Wextra -Werror -pedantic)
endif()

if((APPLE AND CMAKE_SYSTEM_PROCESSOR STREQUAL "arm64") OR
   (CMAKE_SYSTEM_NAME STREQUAL "Linux" AND CMAKE_SYSTEM_PROCESSOR MATCHES "^(aarch64|arm64|x86_64|AMD64)$"))
    find_package(Threads REQUIRED)
    find_package(Python3 3.10 REQUIRED COMPONENTS Interpreter)
    # Host integration fixtures exercise the Feather application's named resources.
    set(MICROS_HOST_BOARD "${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/configuration/board.toml" CACHE FILEPATH
        "Board resource definition used by the host application tests")
    execute_process(COMMAND ${Python3_EXECUTABLE} -m micros_tooling.config.configuration
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/configuration/micros.toml" "${MICROS_HOST_BOARD}"
        WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}" COMMAND_ERROR_IS_FATAL ANY)
    set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
        tests/fixtures/configuration/micros.toml "${MICROS_HOST_BOARD}"
        src/micros_tooling/config/configuration.py src/micros_tooling/config/interfaces.py
        src/micros_tooling/config/coordination_codegen.py src/micros_tooling/config/protobuf.py)
    file(GLOB_RECURSE micros_proto_inputs CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/src/sdk/protos/*.proto")
    set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${micros_proto_inputs})
    set(micros_nanopb_sources src/third_party/nanopb/pb_common.c
        src/third_party/nanopb/pb_encode.c src/third_party/nanopb/pb_decode.c)
    add_library(micros_protobuf STATIC ${micros_nanopb_sources})
    target_include_directories(micros_protobuf PUBLIC src/third_party/nanopb)
    target_compile_options(micros_protobuf PRIVATE -Wall -Wextra -Werror)
    # This library is linked into native service images as well as host tests.
    # Host libc hardening helpers would introduce forbidden ELF imports.
    set_target_properties(micros_protobuf PROPERTIES POSITION_INDEPENDENT_CODE ON)
    target_compile_options(micros_protobuf PRIVATE -ffreestanding -fno-builtin -fno-stack-protector)
    set(micros_test_protobuf micros_protobuf)
    if(MICROS_ENABLE_SANITIZERS)
        # Test the codec itself under sanitizers without instrumenting loadable service images.
        add_library(micros_protobuf_checks STATIC ${micros_nanopb_sources})
        target_include_directories(micros_protobuf_checks PUBLIC src/third_party/nanopb)
        set(micros_test_protobuf micros_protobuf_checks)
    endif()
    add_library(micros_image STATIC src/firmware/kernel/loader/image.c src/firmware/kernel/loader/elf.c)
    target_link_libraries(micros_image PUBLIC micros_abi)
    target_include_directories(micros_image PUBLIC src/firmware/kernel/loader)
    add_executable(micros-host tests/harness/loader_main.c)
    target_link_libraries(micros-host PRIVATE micros_image Threads::Threads ${CMAKE_DL_LIBS})
    target_compile_options(micros-host PRIVATE -Wall -Wextra -Werror)
    target_compile_options(micros_image PRIVATE -Wall -Wextra -Werror)
    foreach(variant v1 v2)
        add_library(hello_${variant} SHARED tests/fixtures/loader-service/service.c)
        target_link_libraries(hello_${variant} PRIVATE micros_abi)
        target_compile_options(hello_${variant} PRIVATE -ffreestanding -fno-builtin -fno-stack-protector -Wall -Wextra -Werror)
        target_compile_definitions(hello_${variant} PRIVATE MICROS_SERVICE_TARGET=MICROS_BUILD_TARGET MICROS_SERVICE_VARIANT="${variant}")
        # A dylib filetype is part of the M1 host profile.
        if(APPLE)
            set_target_properties(hello_${variant} PROPERTIES BUNDLE FALSE SUFFIX ".dylib")
        endif()
        add_custom_command(OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/hello_${variant}.mimg"
            COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/src/micros_tooling/storage/native_image.py"
                $<TARGET_FILE:hello_${variant}> "${CMAKE_CURRENT_BINARY_DIR}/hello_${variant}.mimg"
            DEPENDS hello_${variant} src/micros_tooling/storage/native_image.py VERBATIM)
        add_custom_target(package_${variant} ALL DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/hello_${variant}.mimg")
    endforeach()
    add_library(hung_service SHARED tests/integration/hung_service.c)
    target_link_libraries(hung_service PRIVATE micros_abi)
    if(APPLE)
        set_target_properties(hung_service PROPERTIES BUNDLE FALSE SUFFIX ".dylib")
    endif()
    add_custom_command(OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/hung.mimg"
        COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/src/micros_tooling/storage/native_image.py"
            $<TARGET_FILE:hung_service> "${CMAKE_CURRENT_BINARY_DIR}/hung.mimg"
        DEPENDS hung_service src/micros_tooling/storage/native_image.py VERBATIM)
    add_custom_target(package_hung ALL DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/hung.mimg")
    add_library(micros_runtime STATIC src/firmware/controller/support/network_status.c src/firmware/controller/protocol/ipc_console.c src/firmware/controller/application.c src/firmware/controller/status.c src/firmware/kernel/runtime/runtime.c src/firmware/kernel/ipc/channel.c src/firmware/platforms/posix/src/platform.c)
    target_include_directories(micros_runtime PUBLIC src/firmware/controller/include src/firmware/kernel/runtime src/firmware/kernel/ipc src/firmware/contracts/include)
    target_link_libraries(micros_runtime PUBLIC micros_image Threads::Threads ${CMAKE_DL_LIBS})
    target_compile_options(micros_runtime PRIVATE -Wall -Wextra -Werror)
    add_executable(micros-runtime tests/harness/runtime_main.c)
    target_link_libraries(micros-runtime PRIVATE micros_runtime)
    target_compile_options(micros-runtime PRIVATE -Wall -Wextra -Werror)
    add_executable(application-controller-tests tests/runtime/application_controller_test.c)
    target_link_libraries(application-controller-tests PRIVATE micros_runtime)
    add_executable(management-status-tests tests/runtime/status_test.c)
    target_link_libraries(management-status-tests PRIVATE micros_runtime)
    add_executable(micros-control
        src/firmware/platforms/posix/sdk/main.c
        src/firmware/controller/controller.c src/firmware/controller/deployment.c
        src/firmware/kernel/deployment/activation.c src/firmware/kernel/hash/sha256.c
        src/firmware/platforms/posix/src/storage.c src/firmware/platforms/posix/src/transport.c
        src/firmware/platforms/posix/src/network.c src/firmware/platforms/posix/src/update.c
        src/firmware/platforms/posix/src/telemetry.c)
    target_include_directories(micros-control PRIVATE src/firmware/kernel/deployment src/firmware/kernel/hash src/firmware/kernel/loader)
    target_link_libraries(micros-control PRIVATE micros_runtime)
    target_compile_options(micros-control PRIVATE -Wall -Wextra -Werror)
    add_executable(micros-pipeline tests/harness/pipeline_main.c)
    target_link_libraries(micros-pipeline PRIVATE micros_runtime)
    target_compile_options(micros-pipeline PRIVATE -Wall -Wextra -Werror)
    set(pipeline_role 0)
    foreach(participant publisher fast slow)
        add_library(pipeline_${participant} SHARED tests/fixtures/sensor-pipeline/src/service.c examples/services/button/generated/button_state.pb.c)
        target_link_libraries(pipeline_${participant} PRIVATE micros_abi micros_protobuf)
        target_include_directories(pipeline_${participant} PRIVATE src/sdk/c/include examples/services/button/generated)
        target_compile_definitions(pipeline_${participant} PRIVATE PIPELINE_ROLE=${pipeline_role})
        target_compile_options(pipeline_${participant} PRIVATE -ffreestanding -fno-builtin -fno-stack-protector -Wall -Wextra -Werror)
        add_custom_command(OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/pipeline_${participant}.mimg"
            COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/src/micros_tooling/storage/native_image.py"
                $<TARGET_FILE:pipeline_${participant}> "${CMAKE_CURRENT_BINARY_DIR}/pipeline_${participant}.mimg"
            DEPENDS pipeline_${participant} src/micros_tooling/storage/native_image.py VERBATIM)
        add_custom_target(package_pipeline_${participant} ALL DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/pipeline_${participant}.mimg")
        math(EXPR pipeline_role "${pipeline_role} + 1")
    endforeach()
    # Compile the physical GPIO driver and LED consumer unchanged against host BSP simulation.
    foreach(board_role 0 1 3)
        if(board_role EQUAL 0)
            set(board_source tests/fixtures/sensor-pipeline/src/service.c)
        elseif(board_role EQUAL 1)
            set(board_source examples/services/logger/src/service.c examples/services/logger/generated/logger_ipc.c)
        else()
            set(board_source tests/fixtures/sensor-pipeline/src/service.c)
        endif()
        add_library(board_${board_role} SHARED ${board_source} examples/services/button/generated/button_state.pb.c)
        target_link_libraries(board_${board_role} PRIVATE micros_abi micros_protobuf)
        target_include_directories(board_${board_role} PRIVATE src/sdk/c/include examples/services/button/generated)
        if(NOT board_role EQUAL 1)
            target_compile_definitions(board_${board_role} PRIVATE PIPELINE_ROLE=${board_role} PIPELINE_HARDWARE=1)
        endif()
        target_compile_options(board_${board_role} PRIVATE -ffreestanding -fno-builtin -fno-stack-protector -Wall -Wextra -Werror)
        add_custom_command(OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/board_${board_role}.mimg"
            COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/src/micros_tooling/storage/native_image.py"
                $<TARGET_FILE:board_${board_role}> "${CMAKE_CURRENT_BINARY_DIR}/board_${board_role}.mimg"
            DEPENDS board_${board_role} src/micros_tooling/storage/native_image.py VERBATIM)
        add_custom_target(package_board_${board_role} ALL DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/board_${board_role}.mimg")
    endforeach()
    add_library(runtime_service SHARED tests/fixtures/runtime-service/src/service.c)
    target_link_libraries(runtime_service PRIVATE micros_abi)
    target_compile_options(runtime_service PRIVATE -ffreestanding -fno-builtin -fno-stack-protector -Wall -Wextra -Werror)
    add_custom_command(OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/runtime.mimg"
        COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/src/micros_tooling/storage/native_image.py"
            $<TARGET_FILE:runtime_service> "${CMAKE_CURRENT_BINARY_DIR}/runtime.mimg"
        DEPENDS runtime_service src/micros_tooling/storage/native_image.py VERBATIM)
    add_custom_target(package_runtime ALL DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/runtime.mimg")
    add_library(cpp_service SHARED tests/fixtures/cpp-lifecycle/service.cpp)
    target_link_libraries(cpp_service PRIVATE micros_abi)
    set_target_properties(cpp_service PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED YES)
    target_compile_options(cpp_service PRIVATE -ffreestanding -fno-builtin -fno-stack-protector
        "$<$<COMPILE_LANGUAGE:CXX>:-fno-exceptions;-fno-rtti;-fno-threadsafe-statics>" -Wall -Wextra -Werror)
    add_custom_command(OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/cpp.mimg"
        COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/src/micros_tooling/storage/native_image.py"
            $<TARGET_FILE:cpp_service> "${CMAKE_CURRENT_BINARY_DIR}/cpp.mimg"
        DEPENDS cpp_service src/micros_tooling/storage/native_image.py VERBATIM)
    add_custom_target(package_cpp ALL DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/cpp.mimg")
    enable_testing()
    add_executable(fixed-pool-tests tests/runtime/fixed_pool_test.c)
    target_compile_options(fixed-pool-tests PRIVATE -Wall -Wextra -Werror -UNDEBUG)
    add_test(NAME fixed_memory_pool COMMAND fixed-pool-tests)
    add_library(configured_service SHARED tests/configuration/service.c)
    target_link_libraries(configured_service PRIVATE micros_abi)
    target_include_directories(configured_service PRIVATE examples/services/button/generated examples/services/colors/generated)
    target_compile_options(configured_service PRIVATE -ffreestanding -fno-builtin -fno-stack-protector -Wall -Wextra -Werror)
    add_custom_command(OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/configured.mimg"
        COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/src/micros_tooling/storage/native_image.py"
            $<TARGET_FILE:configured_service> "${CMAKE_CURRENT_BINARY_DIR}/configured.mimg"
        DEPENDS configured_service src/micros_tooling/storage/native_image.py VERBATIM)
    add_custom_target(package_configured ALL DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/configured.mimg")
    add_test(NAME application_controller COMMAND application-controller-tests "${CMAKE_CURRENT_BINARY_DIR}")
    add_test(NAME management_status COMMAND management-status-tests)
    add_test(NAME portable_integers COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/platforms/integer_test.py")
    add_test(NAME portable_rpc COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/platforms/rpc_integer_test.py")
    add_test(NAME platform_contract COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/platforms/contract_test.py")
    add_test(NAME shared_controller COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/platforms/controller_test.py" "${CMAKE_CURRENT_BINARY_DIR}")
    set_tests_properties(shared_controller PROPERTIES TIMEOUT 60)
    add_test(NAME repository_paths COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/configuration/repository_test.py")
    add_test(NAME documentation_links COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/docs/links_test.py")
    add_test(NAME external_host_deployment COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/deployment/external_host_test.py"
        "$<TARGET_FILE:micros-control>")
    set_tests_properties(external_host_deployment PROPERTIES TIMEOUT 600)
    add_test(NAME setup_prerequisites COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/cli/setup_test.py")
    add_test(NAME launcher_parity COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/cli/launcher_test.py")
    add_test(NAME application_command_defaults COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/configuration/application_test.py")
    add_test(NAME installed_cli_resolver COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/cli/sdk_test.py")
    add_test(NAME onboarding_defaults COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/cli/onboarding_defaults_test.py")
    add_test(NAME experimental_prepare COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/cli/experimental_prepare_test.py")
    add_test(NAME embedded_rollback_guards COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/base_ota/rollback_guards_test.py")
    add_test(NAME external_application COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/configuration/external_application_test.py")
    add_test(NAME unit_configuration COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/configuration/unit_test.py")
    add_test(NAME service_contract COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/configuration/service_contract_test.py")
    add_test(NAME declaration_model COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/configuration/declaration_model_test.py")
    add_test(NAME named_declarations COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/configuration/named_declarations_test.py")
    add_test(NAME chip_capabilities COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/configuration/chips_test.py")
    add_test(NAME deployment_composition COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/configuration/composition_test.py")
    add_test(NAME physical_setup_composition COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/configuration/setup_test.py")
    add_test(NAME deployment_configuration COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/configuration/configuration_test.py" "${CMAKE_CURRENT_BINARY_DIR}")

    add_test(NAME generated_ipc_interface COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/interfaces/generated_ipc_test.py")

    add_test(NAME generated_coordination_callbacks COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/interfaces/coordination_callbacks_test.py")

    add_test(NAME coordination_evidence_selection COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/hardware/evidence_test.py")

    # Build and load the minimal public examples independently of richer test fixtures.
    foreach(language c cpp)
        if(language STREQUAL "c")
            set(example_source examples/hello-service/src/service.c)
        else()
            set(example_source examples/cpp-service/src/service.cpp)
        endif()
        add_library(minimal_${language} SHARED ${example_source})
        target_link_libraries(minimal_${language} PRIVATE micros_abi)
        set_target_properties(minimal_${language} PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED YES)
        target_compile_options(minimal_${language} PRIVATE -ffreestanding -fno-builtin
            -fno-stack-protector -Wall -Wextra -Werror
            "$<$<COMPILE_LANGUAGE:CXX>:-fno-exceptions;-fno-rtti;-fno-threadsafe-statics>")
        add_custom_command(OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/minimal_${language}.mimg"
            COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/src/micros_tooling/storage/native_image.py"
                $<TARGET_FILE:minimal_${language}> "${CMAKE_CURRENT_BINARY_DIR}/minimal_${language}.mimg"
            DEPENDS minimal_${language} src/micros_tooling/storage/native_image.py VERBATIM)
        add_custom_target(package_minimal_${language} ALL
            DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/minimal_${language}.mimg")
        if(language STREQUAL "c")
            add_test(NAME hello_serial_timer COMMAND ${Python3_EXECUTABLE}
                "${CMAKE_CURRENT_SOURCE_DIR}/tests/integration/hello_timer.py"
                "${CMAKE_CURRENT_BINARY_DIR}")
        else()
            add_test(NAME minimal_cpp_lifecycle COMMAND micros-host
                "${CMAKE_CURRENT_BINARY_DIR}/minimal_cpp.mimg")
        endif()
    endforeach()

    add_executable(color-cycle-tests tests/services/color_cycle_test.c
        examples/services/colors/src/button_input.c examples/services/colors/src/palette.c
        examples/services/colors/generated/colors_ipc.c examples/services/colors/generated/button_state.pb.c)
    target_link_libraries(color-cycle-tests PRIVATE micros_abi ${micros_test_protobuf})
    target_include_directories(color-cycle-tests PRIVATE examples/services/colors/src examples/services/button/src src/sdk/c/include examples/services/button/generated examples/services/colors/generated)
    target_compile_options(color-cycle-tests PRIVATE -Wall -Wextra -Werror)
    add_test(NAME button_color_cycle COMMAND color-cycle-tests)
    add_executable(button-restart-tests tests/services/button_restart_test.c
        examples/services/colors/src/button_input.c examples/services/colors/generated/colors_ipc.c
        examples/services/button/generated/button_ipc.c examples/services/logger/generated/logger_ipc.c
        examples/services/button/generated/button_state.pb.c src/firmware/kernel/ipc/channel.c src/firmware/platforms/posix/src/platform.c)
    target_include_directories(button-restart-tests PRIVATE src/firmware/kernel/runtime src/firmware/kernel/ipc
        src/firmware/contracts/include examples/services/colors/src examples/services/button/generated)
    target_link_libraries(button-restart-tests PRIVATE micros_image ${micros_test_protobuf} Threads::Threads ${CMAKE_DL_LIBS})
    target_compile_options(button-restart-tests PRIVATE -Wall -Wextra -Werror)
    add_test(NAME button_restart COMMAND button-restart-tests "${CMAKE_CURRENT_BINARY_DIR}/fixture_NORMAL.mimg")

    execute_process(COMMAND ${Python3_EXECUTABLE} -m micros_tooling.config.configuration
        "${CMAKE_CURRENT_SOURCE_DIR}/examples/pin-monitor/micros.toml"
        WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}" COMMAND_ERROR_IS_FATAL ANY)
    set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS examples/pin-monitor/micros.toml
        src/micros_tooling/config/resources.py)
    execute_process(COMMAND ${Python3_EXECUTABLE} -m micros_tooling.config.configuration
        "${CMAKE_CURRENT_SOURCE_DIR}/examples/network-bridge/micros.toml"
        WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}" COMMAND_ERROR_IS_FATAL ANY)
    set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS examples/network-bridge/micros.toml)
    add_executable(network-bridge-tests tests/services/network_bridge_test.c src/firmware/controller/protocol/ipc_console.c
        services/network-bridge/generated/bridge_ipc.c
        services/network-bridge/generated/button_state.pb.c
        src/firmware/kernel/ipc/channel.c src/firmware/platforms/posix/src/platform.c)
    target_include_directories(network-bridge-tests PRIVATE services/network-bridge/generated src/firmware/kernel/runtime src/firmware/kernel/ipc src/firmware/contracts/include)
    target_link_libraries(network-bridge-tests PRIVATE micros_image ${micros_test_protobuf} Threads::Threads ${CMAKE_DL_LIBS})
    target_compile_options(network-bridge-tests PRIVATE -Wall -Wextra -Werror)
    add_test(NAME network_bridge COMMAND network-bridge-tests "${CMAKE_CURRENT_BINARY_DIR}/fixture_NORMAL.mimg")
    add_test(NAME network_bridge_client COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/services/network_bridge_client_test.py")

    add_test(NAME pin_monitor COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/services/pin_monitor_test.py")
    add_test(NAME diagnostic_services COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/diagnostics/services_test.py")
    add_test(NAME diagnostic_clients COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/diagnostics/clients_test.py")

    add_executable(elf-tests tests/loader/elf_test.c src/firmware/kernel/loader/elf.c)
    target_include_directories(elf-tests PRIVATE src/firmware/kernel/loader)
    target_compile_options(elf-tests PRIVATE -Wall -Wextra -Werror)
    add_test(NAME elf_profile COMMAND elf-tests)
    add_test(NAME flash_image_backend COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/flash/flash_test.py")
    add_test(NAME cpp_lifecycle COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/integration/cpp_service.py" $<TARGET_FILE:micros-host>
        "${CMAKE_CURRENT_BINARY_DIR}/cpp.mimg")

    foreach(scenario NORMAL NORMAL_PEER FAIL_INIT FAIL_START FAIL_STEP FAIL_STOP HANG_INIT HANG_START HANG_STEP HANG_STOP HANG_CALLBACK SLOW_INIT SLOW_START SLOW_BOTH SLOW_CALLBACK HANDLE_CHECKS CALLBACK_ERROR)
        add_library(fixture_${scenario} SHARED tests/runtime/fixture.c)
        target_link_libraries(fixture_${scenario} PRIVATE micros_abi)
        if(scenario STREQUAL "NORMAL_PEER")
            target_compile_definitions(fixture_${scenario} PRIVATE FIXTURE_MODE=NORMAL FIXTURE_LINE=1)
        else()
            target_compile_definitions(fixture_${scenario} PRIVATE FIXTURE_MODE=${scenario})
        endif()
        target_compile_options(fixture_${scenario} PRIVATE -ffreestanding -fno-builtin -fno-stack-protector -Wall -Wextra -Werror)
        add_custom_command(OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/fixture_${scenario}.mimg"
            COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/src/micros_tooling/storage/native_image.py"
                $<TARGET_FILE:fixture_${scenario}> "${CMAKE_CURRENT_BINARY_DIR}/fixture_${scenario}.mimg"
            DEPENDS fixture_${scenario} src/micros_tooling/storage/native_image.py VERBATIM)
        add_custom_target(package_fixture_${scenario} ALL DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/fixture_${scenario}.mimg")
    endforeach()
    add_executable(runtime-tests tests/runtime/runtime_test.c src/firmware/kernel/ipc/channel.c src/firmware/platforms/posix/src/platform.c)
    add_executable(selective-deploy-tests tests/deployment/selective_deploy_test.c)
    target_include_directories(selective-deploy-tests PRIVATE tests/flash/mocks src/firmware/platforms/esp32/src/support src/firmware/kernel/deployment)
    target_link_libraries(selective-deploy-tests PRIVATE micros_runtime)
    target_compile_options(selective-deploy-tests PRIVATE -Wall -Wextra -Werror -UNDEBUG)
    add_test(NAME selective_deployment COMMAND selective-deploy-tests "${CMAKE_CURRENT_BINARY_DIR}")
    add_executable(service-restart-command-tests tests/deployment/service_restart_command_test.c)
    target_include_directories(service-restart-command-tests PRIVATE src/firmware/kernel/runtime src/sdk/abi/include src/firmware/controller/include)
    target_compile_options(service-restart-command-tests PRIVATE -Wall -Wextra -Werror -UNDEBUG)
    add_test(NAME service_restart_command COMMAND service-restart-command-tests)
    add_test(NAME service_restart_client COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/deployment/service_control_test.py")
    target_include_directories(runtime-tests PRIVATE src/firmware/kernel/runtime src/firmware/kernel/ipc src/firmware/contracts/include)
    target_link_libraries(runtime-tests PRIVATE micros_image Threads::Threads ${CMAKE_DL_LIBS})
    target_compile_options(runtime-tests PRIVATE -Wall -Wextra -Werror -UNDEBUG)
    add_executable(ipc-tests tests/ipc/channel_test.c src/firmware/kernel/ipc/channel.c src/firmware/platforms/posix/src/platform.c)
    target_include_directories(ipc-tests PRIVATE src/firmware/kernel/runtime src/firmware/kernel/ipc src/firmware/contracts/include)
    target_link_libraries(ipc-tests PRIVATE micros_image Threads::Threads ${CMAKE_DL_LIBS})
    target_compile_options(ipc-tests PRIVATE -Wall -Wextra -Werror -UNDEBUG)
    add_executable(codec-tests tests/ipc/codec_test.c examples/services/button/generated/button_state.pb.c)
    target_include_directories(codec-tests PRIVATE src/sdk/c/include examples/services/button/generated)
    target_link_libraries(codec-tests PRIVATE micros_abi ${micros_test_protobuf})
    target_compile_options(codec-tests PRIVATE -Wall -Wextra -Werror -UNDEBUG)
    add_executable(wifi-credentials-tests tests/deployment/wifi_credentials_test.c src/firmware/controller/support/wifi_credentials.c)
    target_include_directories(wifi-credentials-tests PRIVATE src/firmware/controller/include)
    target_compile_options(wifi-credentials-tests PRIVATE -Wall -Wextra -Werror -UNDEBUG)
    add_test(NAME wifi_credentials COMMAND wifi-credentials-tests)
    add_test(NAME wifi_terminal COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/deployment/wifi_test.py")
    add_test(NAME discovery_terminal COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/deployment/discovery_test.py")
    add_test(NAME erasure_terminal COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/deployment/erasure_test.py")
    add_test(NAME esp8266_bootstrap COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/esp8266/bootstrap_test.py")
    add_test(NAME enrollment_progress COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/deployment/progress_test.py")
    add_test(NAME esp8266_synchronization COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/esp8266/synchronization_test.py")
    add_test(NAME esp8266_tls_setup COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/esp8266/tls_setup_test.py")
    add_test(NAME esp8266_base_poll COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/esp8266/base_poll_test.py")
    add_test(NAME esp8266_base_retry COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/esp8266/base_ota_retry_test.py")
    add_test(NAME esp8266_download COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/esp8266/download_test.py")
    add_test(NAME platform_routing COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/deployment/platform_routing_test.py")
    add_test(NAME samd_enrollment COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/deployment/samd_enrollment_test.py")
    add_test(NAME enrollment_terminal COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/deployment/enrollment_test.py")
    add_test(NAME enrollment_server_selection COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/deployment/server_selection_test.py")
    add_executable(base-ota-tests tests/base_ota/ota_test.c src/firmware/platforms/esp32/src/update.c)
    target_include_directories(base-ota-tests PRIVATE tests/base_ota/fakes src/firmware/controller/include)
    target_compile_options(base-ota-tests PRIVATE -Wall -Wextra -Werror -UNDEBUG)
    foreach(case success slot1 trial write_fail digest_fail end_fail select_fail abort)
        add_test(NAME base_ota_${case} COMMAND base-ota-tests ${case})
    endforeach()
    add_test(NAME base_ota_client COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/base_ota/client_test.py")
    add_test(NAME base_ota_embedded_client COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/base_ota/embedded_test.py")
    add_executable(management-auth-tests tests/deployment/management_auth_test.c src/firmware/controller/support/auth.c)
    target_include_directories(management-auth-tests PRIVATE src/firmware/controller/include)
    target_compile_options(management-auth-tests PRIVATE -Wall -Wextra -Werror -UNDEBUG)
    add_test(NAME management_authentication COMMAND management-auth-tests)
    add_executable(activation-tests tests/deployment/activation_test.c src/firmware/kernel/deployment/activation.c)
    target_include_directories(activation-tests PRIVATE src/firmware/kernel/deployment)
    target_link_libraries(activation-tests PRIVATE micros_image)
    target_compile_options(activation-tests PRIVATE -Wall -Wextra -Werror -UNDEBUG)
    add_test(NAME activation_host COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/deployment/activation_host_test.py" "${CMAKE_CURRENT_BINARY_DIR}")
    set_tests_properties(activation_host PROPERTIES TIMEOUT 45)
    add_test(NAME activation_journal COMMAND activation-tests)
    add_test(NAME board_simulation COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/deployment/board_test.py" "${CMAKE_CURRENT_BINARY_DIR}")
    add_test(NAME interactive_shell COMMAND ${Python3_EXECUTABLE} -m unittest discover
        -s "${CMAKE_CURRENT_SOURCE_DIR}/tests/terminal" -p "*_test.py")
    add_test(NAME service_commands COMMAND ${Python3_EXECUTABLE} -m unittest discover
        -s "${CMAKE_CURRENT_SOURCE_DIR}/tests/commands" -p "*_test.py")
    add_test(NAME terminal_deployment COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/deployment/terminal_test.py")
    add_test(NAME deployment_planning COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/deployment/planning_test.py")
    add_test(NAME management_artifacts COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/server/artifacts_test.py")
    add_test(NAME esp8266_tools COMMAND ${Python3_EXECUTABLE} -m unittest discover
        -s "${CMAKE_CURRENT_SOURCE_DIR}/tests/esp8266" -p "*_test.py")
    add_test(NAME samd21_tools COMMAND ${Python3_EXECUTABLE} -m unittest discover
        -s "${CMAKE_CURRENT_SOURCE_DIR}/tests/samd21" -p "*_test.py")
    add_executable(samd21-http-tests tests/samd21/http_test.cpp)
    target_compile_features(samd21-http-tests PRIVATE cxx_std_17)
    target_include_directories(samd21-http-tests PRIVATE src/firmware/platforms/samd21/src/support)
    target_compile_options(samd21-http-tests PRIVATE -Wall -Wextra -Werror)
    add_test(NAME samd21_http COMMAND samd21-http-tests)
    add_test(NAME management_relay COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/server/relay_test.py")
    add_test(NAME management_coordination COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/server/coordination_test.py")
    add_test(NAME console_offline COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/server/console_unit_test.py")
    set_tests_properties(console_offline PROPERTIES SKIP_RETURN_CODE 77)
    add_test(NAME management_console COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/server/console_test.py")
    add_test(NAME channel_metadata COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/server/channel_metadata_test.py")
    add_test(NAME management_streams COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/server/streams_test.py")
    add_test(NAME management_flash_inventory COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/server/flash_test.py")
    add_test(NAME package_admission COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/deployment/packages_test.py" "${CMAKE_CURRENT_BINARY_DIR}")
    add_test(NAME local_management COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/deployment/control_test.py" "${CMAKE_CURRENT_BINARY_DIR}")
    set_tests_properties(package_admission local_management PROPERTIES TIMEOUT 60)
    add_test(NAME codec_boundaries COMMAND codec-tests)
    add_executable(codec-tool tests/ipc/codec_tool.c examples/services/button/generated/button_state.pb.c)
    target_include_directories(codec-tool PRIVATE src/sdk/c/include examples/services/button/generated)
    target_link_libraries(codec-tool PRIVATE micros_abi ${micros_test_protobuf})
    target_compile_options(codec-tool PRIVATE -Wall -Wextra -Werror)
    add_test(NAME ir_service COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/services/ir_service_test.py")
    add_test(NAME ipc_boundaries COMMAND ipc-tests "${CMAKE_CURRENT_BINARY_DIR}/fixture_NORMAL.mimg")
    add_test(NAME protobuf_interoperability COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/ipc/protobuf_test.py" $<TARGET_FILE:codec-tool>)
    add_test(NAME pipeline_demo COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/ipc/pipeline_test.py" $<TARGET_FILE:micros-pipeline> "${CMAKE_CURRENT_BINARY_DIR}")
    set_tests_properties(ipc_boundaries protobuf_interoperability pipeline_demo PROPERTIES TIMEOUT 30)
    if(MICROS_ENABLE_SANITIZERS)
        # Interoperability starts more than 80 independently instrumented processes.
        # Linux ASan startup adds wall time; each individual codec call still has a 5 s bound.
        set_tests_properties(protobuf_interoperability PROPERTIES TIMEOUT 120)
        # Service images stay freestanding: sanitizer constructors/imports would
        # violate their native profile. Instrument src/firmware/kernel/BSP and test driver.
        foreach(instrumented_target micros_protobuf_checks micros_image micros_runtime runtime-tests ipc-tests codec-tool codec-tests activation-tests management-auth-tests elf-tests color-cycle-tests button-restart-tests network-bridge-tests)
            target_compile_options(${instrumented_target} PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
            target_link_options(${instrumented_target} PUBLIC -fsanitize=address,undefined)
        endforeach()
    endif()
    add_test(NAME runtime_lifecycle COMMAND runtime-tests "${CMAKE_CURRENT_BINARY_DIR}")
    set_tests_properties(runtime_lifecycle PROPERTIES TIMEOUT 20)
    foreach(scenario HANG_INIT HANG_START HANG_STEP HANG_STOP HANG_CALLBACK)
        add_test(NAME runtime_${scenario} COMMAND runtime-tests "${CMAKE_CURRENT_BINARY_DIR}" ${scenario})
        set_tests_properties(runtime_${scenario} PROPERTIES TIMEOUT 5)
    endforeach()

    if(NOT APPLE)
        add_test(NAME linux_native_profile COMMAND ${Python3_EXECUTABLE}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/loader/linux_profile.py" $<TARGET_FILE:micros-host> ${CMAKE_C_COMPILER})
        get_property(all_targets DIRECTORY PROPERTY BUILDSYSTEM_TARGETS)
        foreach(service_target IN LISTS all_targets)
            get_target_property(target_type ${service_target} TYPE)
            if(target_type STREQUAL "SHARED_LIBRARY")
                target_sources(${service_target} PRIVATE src/sdk/c/src/freestanding.c)
                target_link_options(${service_target} PRIVATE -nostdlib -Wl,-Bsymbolic -Wl,--no-undefined)
                if(CMAKE_C_COMPILER_ID STREQUAL "GNU")
                    target_compile_options(${service_target} PRIVATE -fno-tree-loop-distribute-patterns)
                endif()
            endif()
        endforeach()
    endif()
    add_test(NAME host_loader COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/integration/host_loader.py"
        $<TARGET_FILE:micros-host> "${CMAKE_CURRENT_BINARY_DIR}")
    get_property(micros_tests DIRECTORY PROPERTY TESTS)
    set_property(TEST ${micros_tests} APPEND PROPERTY
        ENVIRONMENT "PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}/src")
endif()
