# Propagate explicitly selected feature requirements to every production source.
foreach(capability NATIVE_SERVICES PERSISTENT_STORAGE BASE_UPDATE SELECTIVE_UPDATE HARDWARE_TELEMETRY USB_BOOTLOADER ANALOG_GPIO)
    if(DEFINED MICROS_REQUIRE_${capability})
        if(MICROS_REQUIRE_${capability})
            add_compile_definitions(MICROS_REQUIRE_${capability}=1)
        endif()
    endif()
endforeach()
