include("${CMAKE_CURRENT_LIST_DIR}/../../../../contracts/requirements.cmake")
set(MICROS_ENTRY_SOURCE "main.cpp")
if(MICROS_TEST_HUNG_BASE)
    set(MICROS_ENTRY_SOURCE "../../../../../../tests/esp8266/hung_main.cpp")
endif()
set(COMPONENT_SRCS "${MICROS_ENTRY_SOURCE}" "../../src/platform.c" "../../src/support/system.cpp" "../../src/storage.c"
    "../../src/network.cpp" "../../src/update.cpp" "../../../../controller/application.c" "../../../../controller/support/network_status.c" "../../../../controller/controller.c" "../../../../controller/deployment.c"
    "../../../../controller/status.c" "../../../../controller/protocol/ipc_console.c"
    "../../src/transport.cpp" "../../src/telemetry.cpp"
    "../../../../kernel/runtime/runtime.c" "../../../../kernel/ipc/channel.c"
    "../../../../kernel/loader/image.c" "../../../../kernel/loader/elf.c"
    "../../../../kernel/deployment/activation.c" "../../../../kernel/hash/sha256.c")
set(COMPONENT_ADD_INCLUDEDIRS "../.." "../../../../kernel/support" "../../src/support" "../../../../controller/include" "../../../../../sdk/abi/include" "../../../../contracts/include"
    "../../../../kernel/runtime" "../../../../kernel/ipc" "../../../../kernel/loader"
    "../../../../kernel/deployment" "../../../../kernel/hash")
if(MICROS_RELAY_CA)
    set(COMPONENT_EMBED_TXTFILES "${MICROS_RELAY_CA}")
else()
    set(COMPONENT_EMBED_TXTFILES "../certs/relay-roots.pem")
endif()
register_component()
target_compile_definitions(${COMPONENT_LIB} PRIVATE MICROS_RUNTIME_GPIO_CAPACITY=4)
target_compile_options(${COMPONENT_LIB} PRIVATE -Wall -Wextra -Werror
    $<$<COMPILE_LANGUAGE:C>:-std=gnu17> $<$<COMPILE_LANGUAGE:CXX>:-std=gnu++17>)

# Prefer the relay's ECDSA certificate while retaining RSA compatibility.
target_compile_definitions(mbedtls PRIVATE
    MBEDTLS_SSL_CIPHERSUITES=MBEDTLS_TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256,MBEDTLS_TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256)

# Bound temporary signature-verification and key-exchange tables. The library
# defaults exhaust this chip's heap when an application is already running.
# Smaller windows trade computation time for RAM without changing key sizes,
# accepted certificates, cipher suites, or verification requirements.
foreach(tls_target mbedtls mbedx509 mbedcrypto)
    target_compile_definitions(${tls_target} PRIVATE
        MBEDTLS_ECP_WINDOW_SIZE=2 MBEDTLS_ECP_FIXED_POINT_OPTIM=0
        MBEDTLS_MPI_WINDOW_SIZE=2)
endforeach()
