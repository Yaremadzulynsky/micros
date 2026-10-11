#ifndef MICROS_CAPABILITIES_H
#define MICROS_CAPABILITIES_H
/* The build selects one target include directory. No silent default capabilities.
 * Mandatory operations remain ordinary declarations: omission fails at link time.
 * Set MICROS_REQUIRE_<capability>=1 when selecting an optional build feature. */
#include <target_config.h>
#ifndef MICROS_CAP_ANALOG_GPIO
#error "Target must declare MICROS_CAP_ANALOG_GPIO as 0 or 1"
#elif MICROS_CAP_ANALOG_GPIO != 0 && MICROS_CAP_ANALOG_GPIO != 1
#error "MICROS_CAP_ANALOG_GPIO must be 0 or 1"
#endif
#if defined(MICROS_REQUIRE_ANALOG_GPIO) && MICROS_REQUIRE_ANALOG_GPIO && !MICROS_CAP_ANALOG_GPIO
#error "Selected build requires unsupported capability: ANALOG_GPIO"
#endif
#ifndef MICROS_CAP_NATIVE_SERVICES
#error "Target must declare MICROS_CAP_NATIVE_SERVICES as 0 or 1"
#elif MICROS_CAP_NATIVE_SERVICES != 0 && MICROS_CAP_NATIVE_SERVICES != 1
#error "MICROS_CAP_NATIVE_SERVICES must be 0 or 1"
#endif
#if defined(MICROS_REQUIRE_NATIVE_SERVICES) && MICROS_REQUIRE_NATIVE_SERVICES && !MICROS_CAP_NATIVE_SERVICES
#error "Selected build requires unsupported capability: NATIVE_SERVICES"
#endif
#ifndef MICROS_CAP_PERSISTENT_STORAGE
#error "Target must declare MICROS_CAP_PERSISTENT_STORAGE as 0 or 1"
#elif MICROS_CAP_PERSISTENT_STORAGE != 0 && MICROS_CAP_PERSISTENT_STORAGE != 1
#error "MICROS_CAP_PERSISTENT_STORAGE must be 0 or 1"
#endif
#if defined(MICROS_REQUIRE_PERSISTENT_STORAGE) && MICROS_REQUIRE_PERSISTENT_STORAGE && !MICROS_CAP_PERSISTENT_STORAGE
#error "Selected build requires unsupported capability: PERSISTENT_STORAGE"
#endif
#ifndef MICROS_CAP_BASE_UPDATE
#error "Target must declare MICROS_CAP_BASE_UPDATE as 0 or 1"
#elif MICROS_CAP_BASE_UPDATE != 0 && MICROS_CAP_BASE_UPDATE != 1
#error "MICROS_CAP_BASE_UPDATE must be 0 or 1"
#endif
#if defined(MICROS_REQUIRE_BASE_UPDATE) && MICROS_REQUIRE_BASE_UPDATE && !MICROS_CAP_BASE_UPDATE
#error "Selected build requires unsupported capability: BASE_UPDATE"
#endif
#ifndef MICROS_CAP_SELECTIVE_UPDATE
#error "Target must declare MICROS_CAP_SELECTIVE_UPDATE as 0 or 1"
#elif MICROS_CAP_SELECTIVE_UPDATE != 0 && MICROS_CAP_SELECTIVE_UPDATE != 1
#error "MICROS_CAP_SELECTIVE_UPDATE must be 0 or 1"
#endif
#if defined(MICROS_REQUIRE_SELECTIVE_UPDATE) && MICROS_REQUIRE_SELECTIVE_UPDATE && !MICROS_CAP_SELECTIVE_UPDATE
#error "Selected build requires unsupported capability: SELECTIVE_UPDATE"
#endif
#ifndef MICROS_CAP_HARDWARE_TELEMETRY
#error "Target must declare MICROS_CAP_HARDWARE_TELEMETRY as 0 or 1"
#elif MICROS_CAP_HARDWARE_TELEMETRY != 0 && MICROS_CAP_HARDWARE_TELEMETRY != 1
#error "MICROS_CAP_HARDWARE_TELEMETRY must be 0 or 1"
#endif
#if defined(MICROS_REQUIRE_HARDWARE_TELEMETRY) && MICROS_REQUIRE_HARDWARE_TELEMETRY && !MICROS_CAP_HARDWARE_TELEMETRY
#error "Selected build requires unsupported capability: HARDWARE_TELEMETRY"
#endif
#ifndef MICROS_CAP_USB_BOOTLOADER
#error "Target must declare MICROS_CAP_USB_BOOTLOADER as 0 or 1"
#elif MICROS_CAP_USB_BOOTLOADER != 0 && MICROS_CAP_USB_BOOTLOADER != 1
#error "MICROS_CAP_USB_BOOTLOADER must be 0 or 1"
#endif
#if defined(MICROS_REQUIRE_USB_BOOTLOADER) && MICROS_REQUIRE_USB_BOOTLOADER && !MICROS_CAP_USB_BOOTLOADER
#error "Selected build requires unsupported capability: USB_BOOTLOADER"
#endif
#ifdef __cplusplus
#define MICROS_REQUIRE_CAPABILITY(name) static_assert(MICROS_CAP_##name, "Required platform capability: " #name)
#else
#define MICROS_REQUIRE_CAPABILITY(name) _Static_assert(MICROS_CAP_##name, "Required platform capability: " #name)
#endif
#endif
