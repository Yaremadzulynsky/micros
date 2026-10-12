#!/usr/bin/env python3
"""Build and bind the isolated ESP8266 base; never flash a device."""

import argparse
import os
import re
import ssl
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
SDK_REVISION = "89a3f254b63819035f65d9c5dcdae8864f1a6a8a"


def prepare_relay_ca(source, output):
    """Freeze public trust material per build, never change the shared roots."""
    pem = source.read_text()
    certificate = r"-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\s]+-----END CERTIFICATE-----"
    if not re.fullmatch(r"\s*(?:" + certificate + r"\s*)+", pem):
        raise ValueError("Relay CA must contain only PEM certificates, never private keys")
    # Python 3.10 with OpenSSL 3.6 can reject valid PEM passed as cadata.
    # The file loader validates the same certificates without that compatibility bug.
    ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cafile=str(source))
    destination = output / "trust/relay-roots.pem"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or destination.read_text() != pem:
        destination.write_text(pem)
    return destination.resolve()


def patch_dynamic_tls_setup(source):
    """Avoid buffers that the pinned SDK's dynamic wrapper immediately frees.

    Setup only derives header pointers and initializes handshake structures.
    The wrapper replaces both buffers before any record I/O. Keep full record
    limits unchanged: subsequent allocations still use the received TLS size.
    This patch is only valid with CONFIG_MBEDTLS_DYNAMIC_BUFFER=y.
    """
    start = source.index("int mbedtls_ssl_setup(")
    end = source.index("\nerror:", start)
    setup = source[start:end]
    for direction in ("IN", "OUT"):
        needle = f"mbedtls_calloc( 1, MBEDTLS_SSL_{direction}_BUFFER_LEN )"
        if setup.count(needle) != 1:
            raise ValueError("Unexpected pinned TLS setup source")
        setup = setup.replace(needle, "mbedtls_calloc( 1, MBEDTLS_SSL_HEADER_LEN )")
    return source[:start] + setup + source[end:]


def patch_tls_handshake_diagnostics(source, detailed=False):
    """Log the failed protocol step without certificates, keys, or payloads."""
    needle = 'ESP_LOGE(TAG, "mbedtls_ssl_handshake returned -0x%x", -ret);'
    if source.count(needle) != 1:
        raise ValueError("Unexpected pinned TLS handshake source")
    if not detailed:
        return source.replace(needle, needle + '\n            ESP_LOGE(TAG, "TLS handshake state: %d", tls->ssl.state);')
    source = source.replace('#include "esp_log.h"', '#include "esp_log.h"\n#include "esp_timer.h"\n#include "esp_system.h"')
    call = '    ret = mbedtls_ssl_handshake(&tls->ssl);'
    if source.count(call) != 1:
        raise ValueError("Unexpected pinned handshake call")
    source = source.replace(call, r'''    ret = 0;
    while (tls->ssl.state != MBEDTLS_SSL_HANDSHAKE_OVER) {
        int state = tls->ssl.state;
        unsigned heap = esp_get_free_heap_size();
        int64_t started = esp_timer_get_time();
        ret = mbedtls_ssl_handshake_step(&tls->ssl);
        int cipher = tls->ssl.session_negotiate ? tls->ssl.session_negotiate->ciphersuite : 0;
        ESP_LOGE(TAG, "TLS step=%d next=%d ms=%u heap=%u->%u cipher=%04x result=%d",
                 state, tls->ssl.state, (unsigned)((esp_timer_get_time()-started)/1000),
                 heap, esp_get_free_heap_size(), cipher, ret);
        if (ret != 0) break;
    }''')
    return source.replace(needle, needle + '\n            ESP_LOGE(TAG, "TLS handshake state: %d", tls->ssl.state);')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sdk", type=Path, default=ROOT / "build/toolchains/esp8266-rtos-sdk-v3.4"
    )
    parser.add_argument(
        "--compiler-dir", type=Path, default=ROOT / "build/toolchains/xtensa-lx106-elf/bin"
    )
    parser.add_argument("--python", type=Path, default=ROOT / "build/esp8266/python/bin/python")
    parser.add_argument("--output", type=Path, default=ROOT / "build/esp8266/firmware")
    parser.add_argument("--relay-ca", type=Path,
                        help="PEM certificates trusted by this base (defaults to bundled public roots)")
    parser.add_argument("--tls-diagnostics", action="store_true",
                        help="Log TLS step timing, heap and cipher IDs without key or payload data")
    parser.add_argument("--test-hung-base", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        relay_ca = prepare_relay_ca(args.relay_ca or ROOT / "src/firmware/platforms/esp8266/sdk/certs/relay-roots.pem", args.output)
    except (OSError, ValueError) as error:
        parser.error("Invalid relay CA: " + str(error))
    revision = subprocess.check_output(
        ["git", "-C", str(args.sdk), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != SDK_REVISION:
        parser.error("Use the pinned ESP8266 RTOS SDK v3.4 revision " + SDK_REVISION)
    # This SDK copy belongs exclusively to the ESP8266 build.
    relative = "components/bootloader/subproject/main/bootloader_start.c"
    original = subprocess.check_output(
        ["git", "-C", str(args.sdk), "show", "HEAD:" + relative], text=True
    )
    needle = "int boot_index = selected_boot_partition(&bs);"
    if original.count(needle) != 1:
        parser.error("Unexpected pinned bootloader source")
    patched = original.replace(
        needle, "int boot_index = micros_boot_select(selected_boot_partition(&bs));"
    )
    patched = patched.replace(
        "static const char* TAG",
        '#include "'
        + str(ROOT / "src/firmware/platforms/esp8266/sdk/boot/selector.h")
        + '"\n\nstatic const char* TAG',
    )
    source = args.sdk / relative
    if source.read_text() != patched:
        source.write_text(patched)
    args.output.mkdir(parents=True, exist_ok=True)
    config = args.output / "sdkconfig"
    if not config.exists():
        config.write_text((ROOT / "src/firmware/platforms/esp8266/sdk/sdkconfig.defaults").read_text())
    if "CONFIG_MBEDTLS_DYNAMIC_BUFFER=y" not in config.read_text():
        parser.error("ESP8266 requires SDK dynamic TLS buffers")
    tls_root = args.sdk / "components/mbedtls/mbedtls"
    tls_relative = "library/ssl_tls.c"
    tls_expected = subprocess.check_output(
        ["git", "-C", str(args.sdk), "rev-parse", "HEAD:components/mbedtls/mbedtls"], text=True
    ).strip()
    tls_revision = subprocess.check_output(
        ["git", "-C", str(tls_root), "rev-parse", "HEAD"], text=True
    ).strip()
    if tls_revision != tls_expected:
        parser.error("Use the mbedTLS revision pinned by the ESP8266 SDK")
    tls_original = subprocess.check_output(
        ["git", "-C", str(tls_root), "show", "HEAD:" + tls_relative], text=True
    )
    tls_patched = patch_dynamic_tls_setup(tls_original)
    tls_source = tls_root / tls_relative
    if tls_source.read_text() != tls_patched:
        tls_source.write_text(tls_patched)
    diagnostic_relative = "components/esp-tls/esp_tls_mbedtls.c"
    diagnostic_original = subprocess.check_output(
        ["git", "-C", str(args.sdk), "show", "HEAD:" + diagnostic_relative], text=True
    )
    diagnostic_source = args.sdk / diagnostic_relative
    diagnostic_patched = patch_tls_handshake_diagnostics(diagnostic_original, args.tls_diagnostics)
    if diagnostic_source.read_text() != diagnostic_patched:
        diagnostic_source.write_text(diagnostic_patched)
    env = dict(
        os.environ,
        IDF_PATH=str(args.sdk.resolve()),
        PATH=os.pathsep.join((str(args.python.absolute().parent), str(args.compiler_dir.resolve()), os.environ["PATH"])),
    )
    subprocess.run(
        [
            "cmake",
            "-S",
            str(ROOT / "src/firmware/platforms/esp8266/sdk"),
            "-B",
            str(args.output),
            "-G",
            "Ninja",
            "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
            "-DMICROS_TEST_HUNG_BASE=" + ("ON" if args.test_hung_base else "OFF"),
            "-DMICROS_RELAY_CA=" + str(relay_ca),
            "-DPYTHON=" + str(args.python.absolute()),
            "-DSDKCONFIG=" + str((args.output / "sdkconfig").resolve()),
        ],
        env=env,
        check=True,
    )
    subprocess.run(["cmake", "--build", str(args.output), "-j", "6"], env=env, check=True)
    subprocess.run(
        [
            str(args.compiler_dir / "xtensa-lx106-elf-gcc"),
            "-std=gnu17",
            "-ffreestanding",
            "-I" + str(ROOT / "src/sdk/abi/include"),
            "-c",
            str(ROOT / "tests/esp8266/target_check.c"),
            "-o",
            str(args.output / "target-check.o"),
        ],
        check=True,
    )
    sys.path.insert(0, str(ROOT / "src"))
    from micros_tooling.platforms.esp8266.firmware import bind

    print("Base identity: " + bind(args.output / "micros_esp8266.elf", write=True).hex())


if __name__ == "__main__":
    main()
