#!/usr/bin/env python3
"""Build the isolated MKR bring-up firmware; never flash or contact management."""
import argparse
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[3]
FREERTOS_COMMIT = "dbf70559b27d39c1fdb68dfb9a32140b6a6777a0"


def patch_nina_socket_buffer(source):
    """Bound SPI receive staging and reject allocation failure before driver I/O."""
    size = '#define WIFI_SOCKET_BUFFER_SIZE 1500'
    allocation = '_buffers[socket].data = _buffers[socket].head = (uint8_t*)malloc(WIFI_SOCKET_BUFFER_SIZE);'
    if source.count(size) != 1 or source.count(allocation) != 1:
        raise ValueError('Unexpected pinned WiFiNINA socket buffer source')
    return source.replace(size, '#define WIFI_SOCKET_BUFFER_SIZE 256').replace(
        allocation, allocation + '\n      if (_buffers[socket].data == NULL) return 0;')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freertos", type=Path, default=ROOT / "build/toolchains/freertos-kernel-v11.1.0")
    parser.add_argument("--compiler-dir", type=Path, required=True, help="ARM GCC 10+ bin directory (C17/C++17)")
    parser.add_argument("--output", type=Path, default=ROOT / "build/samd21")
    parser.add_argument("--wifinina", type=Path, default=ROOT / "build/toolchains/wifinina-1.8.14")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--base-slot", type=int, choices=[0,1], default=0)
    parser.add_argument("--require-capability", action="append", default=[],
                        choices=["native_services", "persistent_storage", "base_update", "selective_update",
                                 "hardware_telemetry", "usb_bootloader", "analog_gpio"],
                        help="Require a platform capability; unsupported requirements fail compilation")
    args = parser.parse_args()
    freertos = args.freertos.resolve()
    revision = subprocess.check_output(["git", "-C", str(freertos), "rev-parse", "HEAD"], text=True).strip()
    if revision != FREERTOS_COMMIT:
        parser.error("FreeRTOS must be the pinned V11.1.0 commit " + FREERTOS_COMMIT)
    nina = args.wifinina.resolve()
    require_revision = subprocess.check_output(["git", "-C", str(nina), "rev-parse", "HEAD"], text=True).strip()
    if require_revision != "0de2f03e4ea4e0ced5342153ae77ac1f2cf1afd5":
        parser.error("WiFiNINA must be the pinned 1.8.14 commit")
    compiler = args.compiler_dir.resolve()
    if not (compiler / "arm-none-eabi-gcc").is_file():
        parser.error("--compiler-dir must contain arm-none-eabi-gcc")
    output = args.output.resolve()
    # Patch an isolated build copy; leave the pinned dependency checkout intact.
    nina_copy = output / "wifinina"
    shutil.copytree(nina, nina_copy, dirs_exist_ok=True, ignore=shutil.ignore_patterns('.git'))
    socket_source = nina_copy / "src/utility/WiFiSocketBuffer.cpp"
    socket_source.write_text(patch_nina_socket_buffer(socket_source.read_text()))
    sketch = output / "runtime"
    source = sketch / "src"
    source.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "src/firmware/platforms/samd21/sdk/main.ino", sketch / "runtime.ino")
    sources = {
        "network_status.c": ROOT / "src/firmware/controller/support/network_status.c",
        "application.c": ROOT / "src/firmware/controller/application.c",
        "runtime.c": ROOT / "src/firmware/kernel/runtime/runtime.c",
        "channel.c": ROOT / "src/firmware/kernel/ipc/channel.c",
        "image.c": ROOT / "src/firmware/kernel/loader/image.c",
        "platform.c": ROOT / "src/firmware/platforms/samd21/src/platform.c",
        "platform_support.cpp": ROOT / "src/firmware/platforms/samd21/src/support/system.cpp",
        "deployment.c": ROOT / "src/firmware/controller/deployment.c",
        "status.c": ROOT / "src/firmware/controller/status.c",
        "ipc_console.c": ROOT / "src/firmware/controller/protocol/ipc_console.c",
        "transport.cpp": ROOT / "src/firmware/platforms/samd21/src/transport.cpp",
        "telemetry.cpp": ROOT / "src/firmware/platforms/samd21/src/telemetry.cpp",
        "storage.c": ROOT / "src/firmware/platforms/samd21/src/storage.c",
        "flash.cpp": ROOT / "src/firmware/platforms/samd21/src/support/flash.cpp",
        "network.cpp": ROOT / "src/firmware/platforms/samd21/src/network.cpp",
        "controller.c": ROOT / "src/firmware/controller/controller.c",
        "base_ota.cpp": ROOT / "src/firmware/platforms/samd21/src/update.cpp",
        "reset.cpp": ROOT / "src/firmware/platforms/samd21/src/support/reset.cpp",
        "boot_record.c": ROOT / "src/firmware/platforms/samd21/sdk/boot/record.c",
        "activation.c": ROOT / "src/firmware/kernel/deployment/activation.c",
        "sha256.c": ROOT / "src/firmware/kernel/hash/sha256.c",
        "elf.c": ROOT / "src/firmware/kernel/loader/elf.c",
        "abi_c.c": ROOT / "tools/checks/abi_compile.c",
        "abi_cpp.cpp": ROOT / "tools/checks/abi_compile.cpp",
        "target_check.c": ROOT / "tests/samd21/target_check.c",
        "tasks.c": freertos / "tasks.c",
        "queue.c": freertos / "queue.c",
        "list.c": freertos / "list.c",
        "heap.c": freertos / "portable/MemMang/heap_3.c",
        "port.c": freertos / "portable/GCC/ARM_CM0/port.c",
        "portasm.c": freertos / "portable/GCC/ARM_CM0/portasm.c",
    }
    # Remove only obsolete generated wrappers, never arbitrary user files.
    for old in source.iterdir():
        if old.suffix in ('.c', '.cpp') and old.name not in sources:
            contents = old.read_text()
            if contents.startswith('#include "') and str(ROOT) in contents:
                old.unlink()
    # Compile checks export a fixture query symbol; keep them separate.
    for name, path in sources.items():
        prefix = "#define micros_service_query micros_abi_check_query\n" if name == "abi_c.c" else ""
        if name == "abi_cpp.cpp": prefix = "#define micros_service_query micros_cpp_abi_check_query\n"
        if name == "port.c": prefix = "#define SysTick_Handler micros_freertos_systick\n"
        if name == "portasm.c":
            # LTO can separate the C SVC handler beyond Thumb-1's short branch
            # range. Use an absolute tail branch; r3 is caller-saved, r0 is kept.
            text = path.read_text()
            needle = '"    b vPortSVCHandler_C         ' + chr(92) + 'n"'
            if text.count(needle) != 2:
                parser.error("Unexpected pinned FreeRTOS SVC assembly")
            replacement = '"    ldr r3, =vPortSVCHandler_C ' + chr(92) + 'n"\n' + \
                          '            "    bx r3 ' + chr(92) + 'n"\n' + \
                          '            "    .align 2 ' + chr(92) + 'n"\n' + \
                          '            "    .ltorg ' + chr(92) + 'n"'
            (source / name).write_text(text.replace(needle, replacement))
        else:
            (source / name).write_text(prefix + '#include "' + str(path) + '"\n')
    includes = [ROOT / path for path in ("src/firmware/platforms/samd21", "src/firmware/kernel/support", "src/firmware/controller/include", "src/sdk/abi/include", "src/firmware/contracts/include", "src/firmware/kernel/runtime", "src/firmware/kernel/ipc", "src/firmware/kernel/loader", "src/firmware/kernel/deployment", "src/firmware/kernel/hash", "src/firmware/platforms/samd21/src/support")]
    includes += [freertos / "include", freertos / "portable/GCC/ARM_CM0"]
    common = " ".join('"-I' + str(path) + '"' for path in includes) + " -DMICROS_RUNTIME_GPIO_CAPACITY=4 -DMICROS_RUNTIME_HANDLE_CAPACITY=16u -DMICROS_STATIC_MEMORY=1 -fstack-usage"
    common += "".join(" -DMICROS_REQUIRE_" + capability.upper() + "=1"
                      for capability in args.require_capability)
    core = Path.home() / 'Library/Arduino15/packages/arduino/hardware/samd/1.8.13'
    if not core.is_dir(): core=Path.home()/'.arduino15/packages/arduino/hardware/samd/1.8.13'
    variant=output/'variant'
    shutil.copytree(core/'variants/mkrwifi1010',variant,dirs_exist_ok=True)
    # Micros uses USB CDC and SPI to NINA. It exposes no hardware-UART ABI.
    # The stock variant otherwise retains two unused Uarts and 1 KiB of rings
    # through their interrupt vectors, even with section garbage collection.
    variant_source = variant / 'variant.cpp'
    variant_text = variant_source.read_text()
    uart_start = variant_text.index('// Serial1\nUart Serial1(')
    uart_tail = variant_text[uart_start:]
    if uart_tail.count('Uart Serial') != 2 or not uart_tail.rstrip().endswith('}'):
        raise ValueError('Unexpected pinned MKR UART variant source')
    variant_source.write_text(variant_text[:uart_start])
    script=variant/'linker_scripts/gcc/flash_with_bootloader.ld'
    text=script.read_text().replace('0x00000000+0x2000, LENGTH = 0x00040000-0x2000',
        f'0x{0x4000+args.base_slot*0x14000:08x}, LENGTH = 0x14000')
    script.write_text(text)
    boot=ROOT/'src/firmware/platforms/samd21/sdk/boot'
    subprocess.run([str(compiler/'arm-none-eabi-gcc'),'-mcpu=cortex-m0plus','-mthumb','-Os',
        '-ffreestanding','-fno-builtin','-nostdlib','-ffunction-sections','-fdata-sections',
        '-Wall','-Wextra','-Werror','-Wl,--gc-sections','-Wl,-T,'+str(boot/'selector.ld'),
        str(boot/'selector.c'),str(boot/'record.c'),'-lgcc','-o',str(output/'selector.elf')],check=True)
    subprocess.run([str(compiler/'arm-none-eabi-objcopy'),'-O','binary',str(output/'selector.elf'),str(output/'selector.bin')],check=True)
    # Arduino can retain object files for removed generated wrappers; rebuild
    # its cache so a renamed platform source is never linked twice.
    subprocess.run([
        "arduino-cli", "compile", "--clean", *(["--verbose"] if args.verbose else []), "--fqbn", "arduino:samd:mkrwifi1010", "--library", str(nina_copy),
        "--build-property", "build.variant.path="+str(variant),
        "--build-path", str(output / "objects"), "--output-dir", str(output / "firmware"),
        "--build-property", "compiler.path=" + str(compiler) + "/",
        "--build-property", "compiler.ar.cmd=arm-none-eabi-gcc-ar",
        "--build-property", "compiler.c.extra_flags=-std=gnu17 -flto " + common,
        "--build-property", "compiler.cpp.extra_flags=-std=gnu++17 -flto " + common,
        "--build-property", "compiler.c.elf.extra_flags=-fstack-usage -flto -flto-partition=1to1 -Wl,-T," + str(ROOT / "src/firmware/platforms/samd21/src/support/base_limits.ld") + " -Wl,--undefined=micros_samd21_profile -Wl,--undefined=exception_table",
        str(sketch),
    ], check=True)


if __name__ == "__main__":
    main()
