# V1 native image profile

Status: Implemented format 1 (host/legacy RAM) and format 2 (ESP32 flash).
The [public ABI header](../../../../src/sdk/abi/include/micros/service.h) defines the current
experimental major/revision; images must match exactly. A `.mimg` envelope holds
one native executable image; `.msp` adds the manifest, encoded startup configuration
and interface schemas. Native services are trusted code. Validation enforces this
supported profile; it is not a complete object-format verifier or a security sandbox.

## Envelope

The first 64 bytes are sixteen little-endian unsigned 32-bit words. Parse fields explicitly. File length must equal `64 + code_bytes + data_bytes` and may not exceed the 4 MiB host image class. Device slot/staging limits are stricter.

| Byte offset | Field | Meaning |
| --- | --- | --- |
| 0 | magic | `0x3152434d`, bytes `MCR1` |
| 4 | format | `1` host/legacy RAM; `2` ESP32 flash |
| 8 | target | `1` macOS ARM64; `2` ESP32 Xtensa; `3` Linux ARM64; `4` Linux x86-64; `5` ARMv6-M; `6` ESP8266 Xtensa call0 |
| 12 | ABI major | `0` |
| 16 | ABI revision | Exact match to `MICROS_ABI_REVISION` in the public header |
| 20, 24 | code/data bases | Device slot addresses; zero on host |
| 28 | code bytes | MCU instruction/literal payload or host shared-library file bytes |
| 32 | data bytes | Initialized MCU data/constants/descriptor; zero on host |
| 36 | BSS bytes | Zeroed MCU bytes following initialized data; zero on host |
| 40 | descriptor offset | Offset in MCU initialized data; zero on host |
| 44 | checksum | zlib-compatible CRC-32 of code and data payload |
| 48 | reserved / read-only alias | Zero in format 1; DROM base in format 2 |
| 52 | reserved / read-only suffix | Zero in format 1; read-only suffix length in format 2 |
| 56–63 | reserved | Two zero words |

CRC detects accidental corruption, not authentication. Packages carry SHA-256 image/schema identities, while the device journal binds each selected graph and its referenced images to a content digest.

## ESP32

The default ESP32 base uses [flash-backed service slots](flash-services.md): four
instruction/constant budgets and configurable writable RAM slots (1 KiB by default).
The current [flash linker profile](../../../../src/firmware/platforms/esp32/runtime/main/flash_slots.ld)
exports a 12 KiB code capacity per slot; earlier flash profiles used 8 KiB. The legacy
RAM profile reserves four 8 KiB IRAM slots and defaults to 4 KiB writable slots.
The builder reads exported capacities and slot addresses from the base ELF and
independently links a freestanding Xtensa executable to them. It emits code/data/BSS
and the constant descriptor location. No service object is linked into base firmware.
Undefined imports, runtime relocations, unexpected allocated sections and overflow
are rejected. Compiler-resolved relocations are not device relocation support.

Device admission rejects mismatched slot bases, duplicate slots and manifest/descriptor budget mismatch before hooks execute. The flash loader maps the immutable service bank into IROM and DROM, copies only initialized writable data and the descriptor, and zeroes BSS. The legacy RAM loader uses aligned volatile 32-bit IRAM writes and instruction synchronization. Every lifecycle hook must lie inside loaded code. It inspects the descriptor directly rather than invoking the host discovery query.

Startup configuration occupies up to 256 bytes of runtime-owned storage per instance, separate from executable/data slots and the writable arena. The service decodes typed values into its arena before using them.

Slot addresses are specific to a base layout. Relink all services when physically replacing a base that moves them. PSRAM is outside executable, arena and stack budgets. [M5](../milestones/M5.md) records the hardware integration; [M6](../milestones/M6.md) defines persistent service storage.

## Hosts

Host payloads use native calling conventions and `dlopen`. Each load uses a unique temporary path, validates the native descriptor, and retains the library until workers/callbacks are quiescent and joined. Unload then resets globals/BSS on subsequent loading. File bytes and requested arenas are accounted separately from host dynamic-loader bookkeeping and resident memory.

macOS ARM64 uses a restricted Mach-O dylib with bounded load-command/section parsing and no constructor/TLS sections. Linux uses little-endian ELF64 `ET_DYN`, machine AArch64 (183) or x86-64 (62), bounded file tables and a mapped span at most 4 MiB. The profile rejects writable executable loads, TLS, interpreters, constructors/destructors, imported dependencies/symbols, IFUNC resolvers, nodelete/static-TLS behavior and unsupported relocation classes. Linux services link without hosted startup libraries; only ordinary pointer/data RELA relocations are supported. Kernel-owned libc/pthread use remains in the host adapter.

Service stacks are rounded to at least 64 KiB and the host's runtime `SC_THREAD_STACK_MIN`. The tested Linux ARM64 environment requires 128 KiB; macOS ARM64 and Linux x86-64 use the 64 KiB policy floor. Device workers retain their separately admitted 4 KiB request in the demo.

## Languages and history

C17 and freestanding C++17 are tested. No exceptions, RTTI, TLS, dynamic global initialization or hosted-library imports are supported. C++ uses placement construction and explicit destruction in admitted state. Object-lifetime checks live in `tests/fixtures/cpp-lifecycle/`; the [minimal C++ service](../../../../examples/cpp-service/README.md) needs no state.

M1 originally used one 16 KiB/8 KiB slot and RAM-only `LOAD`/`RUN` transport. That historical harness remains under `archive/esp32-m1`; the V1 entry point is `platforms/esp32/runtime` with four slots, persistent banks and transactional management. Historical milestone evidence describes the firmware tested at that time, not current limits.
