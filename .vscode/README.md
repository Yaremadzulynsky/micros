# micros in VS Code

Microsoft C/C++ uses the generated compile databases, so includes and defines match the build rather than an unrelated global compiler configuration.

- **micros (ESP32 + host)** is the initial profile. ESP32 entries take precedence for shared sources, while host-only sources use their own commands.
- **micros (host first)** prefers host commands for shared sources. Select it with **C/C++: Select a Configuration** when working on host behavior.
- The public ABI and SDK include paths are available as a fallback for headers. Compiler selection comes from each compile command. Do not set a profile-wide `compilerPath`: it overrides the per-file compiler and can send host flags such as `-arch arm64` to Xtensa GCC.
- Host configuration resolves the macOS SDK with `xcrun` and records `-isysroot` in the compile database, so standard headers such as `string.h` resolve even when the editor does not discover the SDK itself. An explicitly selected CMake SDK is preserved.
- The ESP32 fallback includes the pinned compiler's GCC and Newlib headers explicitly. Keep these paths aligned with the ESP-IDF toolchain when upgrading; do not mix macOS system headers into ESP32 sources.

Run **Tasks: Run Task → micros: configure host IntelliSense** or **micros: configure ESP32 IntelliSense** after changing target configuration. **micros: build host** is the default build task. These tasks do not flash hardware.

The settings target the current macOS/Homebrew installation and the existing Python 3.10 ESP-IDF environment for firmware tasks. Python editing uses the isolated host environment in `build/python`; create it with **micros: setup host Python** on a fresh checkout. Another machine may need to update the compiler, CMake, and Python paths. Compiler-query information and actual compile commands drive parsing; Microsoft C/C++ does not offer a dedicated Xtensa instruction-level IntelliSense mode. Use the real ESP32 build for target correctness.

If an already-open editor retains stale diagnostics, run **C/C++: Reset IntelliSense Database**, then **Developer: Reload Window**. Do not silence error squiggles to mask missing headers.

Configuration keys follow the [official C/C++ settings reference](https://code.visualstudio.com/docs/cpp/customize-cpp-settings).

The ESP32 task selects `examples/hello-service/boards/feather.toml` and the current runtime in
`src/firmware/platforms/esp32/sdk/`, using the existing `build/esp32-board-config/`
configuration. Prepare that configuration with the documented ESP32 base builder
first; select a different board explicitly when working on another target.
