# Runtime service

An independently built revision-2 host service. Init acquires one simulated GPIO line; start reserves one periodic timer; each callback toggles the line and writes diagnostics. Stop closes both resources, including after partial initialization. State lives entirely in the loader-provided arena.

Build with the root CMake project and run `build/host/micros-runtime build/host/runtime.mimg`. The M1 ESP32 harness does not implement these resource callbacks yet.
