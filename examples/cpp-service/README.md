# Minimal C++ service

`src/service.cpp` implements four no-op lifecycle hooks. The C hello example additionally demonstrates a repeating timer. The descriptor and query function have C linkage so the native loader can discover them. No classes, placement construction, counters or diagnostic output are needed for this stateless service.

Build through the root CMake project and run `build/host/micros-host build/host/minimal_cpp.mimg`. Compile as freestanding C++17 without exceptions, RTTI or static initialization guards.

The root deployment recipe also defines this skeleton for board testing; enable `services.cpp` to deploy it. The richer object-lifetime and reload checks live in `tests/fixtures/cpp-lifecycle/`. See [the SDK contract](../../docs/archive/documentation/SDK.md) before adding behavior.
