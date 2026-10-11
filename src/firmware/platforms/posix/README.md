# POSIX platform

The six files in `src/` implement the same contracts as the MCU ports. `platform.c`
uses POSIX tasks, synchronization and native loading, with simulated GPIO.
`storage.c` stores two logical image sets and an atomic activation record under
`MICROS_CONTROLLER_STORE`. Network/base-update operations explicitly report their
unsupported or OS-managed behavior. `sdk/main.c` starts the shared controller.

Linux ARM64/x86-64 uses the restricted ELF64 image profile; macOS ARM64 uses Mach-O.
The controller owns health trials, durable attempts and fallback on every target.
The Python host bridge maps package names to native selections and restarts a
process only when the controller requests whole-process recovery.

Loader and runtime demonstrations live in `tests/harness/`. A stuck native hook
requires whole-process recovery; code is never unloaded under a live worker.
