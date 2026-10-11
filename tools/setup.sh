#!/bin/sh
# Bootstrap must run before Python or the SDK environment exists.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
check_only=0
esp32=0
for argument in "$@"; do
    case "$argument" in
        --check) check_only=1 ;;
        --esp32) esp32=1 ;;
        --help|-h)
            echo 'Usage: ./micros setup [--check] [--esp32]'
            echo 'Check and install prerequisites for application development and local builds.'
            echo '  --check  Report readiness without installing or downloading anything.'
            echo '  --esp32  Also install the pinned ESP32 SDK (not supported with --check).'
            exit 0 ;;
        *) echo "Unknown setup option: $argument" >&2; exit 2 ;;
    esac
done
if [ "$check_only" = 1 ] && [ "$esp32" = 1 ]; then
    echo 'Use --check for host prerequisites, or --esp32 to install the board SDK.' >&2
    exit 2
fi
case "$(uname -s)" in
    Darwin) system=macos ;;
    Linux) system=linux ;;
    *) echo 'Micros setup supports macOS and Linux.' >&2; exit 1 ;;
esac
# Also find existing Homebrew installations outside the current PATH.
if [ "$system" = macos ]; then
    for prefix in /opt/homebrew/bin /usr/local/bin; do
        if [ -x "$prefix/brew" ]; then PATH="$PATH:$prefix"; fi
    done
fi
PATH="$ROOT/build/python/bin:$PATH"
export PATH
probe=$(mktemp -d "${TMPDIR:-/tmp}/micros-setup.XXXXXX")
trap 'rm -rf "$probe"' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
supported_python() {
    "$1" -c 'import sys; sys.exit(not ((3, 10) <= sys.version_info[:2] < (3, 13)))' >/dev/null 2>&1
}
find_python() {
    python=
    if [ -n "${MICROS_PYTHON:-}" ]; then
        if supported_python "$MICROS_PYTHON"; then python=$MICROS_PYTHON; fi
        return
    fi
    for candidate in "$ROOT/build/python/bin/python" python3.12 python3.11 python3.10 python3; do
        if supported_python "$candidate"; then python=$candidate; return; fi
    done
}
compiler_ok() {
    # Compile and link against the standard library; command existence is insufficient.
    if [ "$1" = c ]; then
        printf '#include <stdio.h>\nint main(void) { return puts("ready") < 0; }\n' > "$probe/test.c"
        "${CC:-cc}" -std=c17 "$probe/test.c" -o "$probe/c" > "$probe/compiler.log" 2>&1
    else
        printf '#include <string>\nint main() { std::string s("ready"); return s.empty(); }\n' > "$probe/test.cpp"
        "${CXX:-c++}" -std=c++17 "$probe/test.cpp" -o "$probe/cxx" > "$probe/compiler.log" 2>&1
    fi
}
cmake_ok() {
    cmake --version 2>/dev/null | awk 'NR == 1 { split($3, v, "."); ok=(v[1]>3 || (v[1]==3 && v[2]>=24)) } END { exit !ok }'
}
report() {
    if [ "$2" = 1 ]; then printf '  OK       %s\n' "$1"; else printf '  MISSING  %s\n' "$1"; fi
}
scan() {
    git_ok=0; py_ok=0; c_ok=0; cxx_ok=0; build_ok=0; ninja_ok=0; make_ok=0; env_ok=0
    git --version >/dev/null 2>&1 && git_ok=1
    find_python
    if [ -n "$python" ] && "$python" -c 'import venv, ensurepip' >/dev/null 2>&1; then py_ok=1; fi
    compiler_ok c && c_ok=1
    compiler_ok cxx && cxx_ok=1
    cmake_ok && build_ok=1
    ninja --version >/dev/null 2>&1 && ninja_ok=1
    make --version >/dev/null 2>&1 && make_ok=1
    if supported_python "$ROOT/build/python/bin/python" &&
       PYTHONPATH="$ROOT/src" "$ROOT/build/python/bin/python" -c 'from pathlib import Path; from micros_tooling.sdk import check_dependencies; import sys; check_dependencies(Path(sys.argv[1]))' "$ROOT" > "$probe/dependencies.log" 2>&1 &&
       "$ROOT/build/python/bin/python" -m pip check >> "$probe/dependencies.log" 2>&1; then env_ok=1; fi
    printf '\nMicros development prerequisites (%s)\n' "$system"
    report 'Git' "$git_ok"
    report 'Python 3.10–3.12 with venv/pip support' "$py_ok"
    report 'C17 compiler and standard library' "$c_ok"
    report 'C++17 compiler and standard library' "$cxx_ok"
    report 'CMake 3.24+' "$build_ok"
    report 'Ninja' "$ninja_ok"
    report 'Make' "$make_ok"
    report 'SDK Python environment and dependencies' "$env_ok"
    ready=$((git_ok * py_ok * c_ok * cxx_ok * build_ok * ninja_ok * make_ok * env_ok))
    return 0
}
admin() {
    if [ "$(id -u)" = 0 ]; then "$@"
    elif command -v sudo >/dev/null 2>&1; then sudo "$@"
    else echo 'Administrator access is required to install system packages; install them through your administrator and rerun setup.' >&2; exit 1
    fi
}
install_system() {
    if [ "$system" = macos ]; then
        if [ "$c_ok" = 0 ] || [ "$cxx_ok" = 0 ] || [ "$git_ok" = 0 ] || [ "$make_ok" = 0 ]; then
            if ! xcode-select -p >/dev/null 2>&1; then
                xcode-select --install
                echo 'Complete the Apple Command Line Tools installer, then rerun ./micros setup.'
                exit 1
            fi
        fi
        set --
        [ "$git_ok" = 1 ] || set -- "$@" git
        [ "$py_ok" = 1 ] || set -- "$@" python@3.12
        if [ "$#" -gt 0 ]; then
            if ! command -v brew >/dev/null 2>&1; then
                echo 'Install Homebrew from https://brew.sh, then rerun ./micros setup.' >&2
                exit 1
            fi
            printf '\nInstalling with Homebrew: %s\n' "$*"
            brew install "$@"
            if [ "$py_ok" = 0 ]; then
                PATH="$(brew --prefix python@3.12)/bin:$PATH"; export PATH
            fi
        fi
    elif command -v apt-get >/dev/null 2>&1; then
        admin apt-get update
        set --
        [ "$git_ok" = 1 ] || set -- "$@" git
        if [ "$c_ok" = 0 ] || [ "$cxx_ok" = 0 ] || [ "$make_ok" = 0 ]; then set -- "$@" build-essential; fi
        if [ "$py_ok" = 0 ]; then
            py_package=
            if [ -n "$python" ]; then
                py_package=$("$python" -c 'import sys; print("python%d.%d" % sys.version_info[:2])')
            else
                for version in 3.12 3.11 3.10; do
                    if apt-cache show "python$version-venv" >/dev/null 2>&1; then py_package="python$version"; break; fi
                done
            fi
            if [ -z "$py_package" ]; then
                echo 'Your configured apt repositories provide no supported Python. Install Python 3.10–3.12 and set MICROS_PYTHON, then rerun setup.' >&2
                exit 1
            fi
            set -- "$@" "$py_package" "$py_package-venv"
        fi
        printf '\nInstalling with apt: %s\n' "$*"
        admin apt-get install -y "$@"
    elif command -v dnf >/dev/null 2>&1; then
        set --
        [ "$git_ok" = 1 ] || set -- "$@" git
        if [ "$c_ok" = 0 ] || [ "$cxx_ok" = 0 ] || [ "$make_ok" = 0 ]; then set -- "$@" gcc gcc-c++ make; fi
        [ "$py_ok" = 1 ] || set -- "$@" python3.12
        printf '\nInstalling with dnf: %s\n' "$*"
        admin dnf install -y "$@"
    else
        echo 'Automatic system installation requires Homebrew (macOS), apt or dnf (Linux). Install the missing tools with your package manager and rerun setup.' >&2
        exit 1
    fi
}
scan
if [ "$check_only" = 1 ]; then
    if [ "$ready" = 1 ]; then echo 'Ready for application generation, host tests and local builds.'; exit 0; fi
    echo 'Run ./micros setup to install missing prerequisites.'
    exit 1
fi
if [ -n "${MICROS_PYTHON:-}" ] && [ -z "$python" ]; then
    echo 'MICROS_PYTHON must select a working Python 3.10–3.12 interpreter. Correct or unset it and rerun setup.' >&2
    exit 1
fi
if [ -e "$ROOT/build/python" ] && ! supported_python "$ROOT/build/python/bin/python"; then
    echo 'Existing build/python is incomplete or uses unsupported Python. Move it aside and rerun setup; it has been preserved.' >&2
    exit 1
fi
if [ "$git_ok" = 0 ] || [ "$py_ok" = 0 ] || [ "$c_ok" = 0 ] || [ "$cxx_ok" = 0 ] || [ "$make_ok" = 0 ]; then
    install_system
    scan
    if [ "$git_ok" = 0 ] || [ "$py_ok" = 0 ] || [ "$c_ok" = 0 ] || [ "$cxx_ok" = 0 ] || [ "$make_ok" = 0 ]; then
        echo 'System prerequisites remain unavailable. Check the installation output and any CC, CXX or MICROS_PYTHON overrides, then rerun setup.' >&2
        exit 1
    fi
fi
if [ ! -x "$ROOT/build/python/bin/python" ]; then "$python" -m venv "$ROOT/build/python"; fi
python="$ROOT/build/python/bin/python"
if [ "$env_ok" = 0 ]; then
    "$python" -m pip install -r "$ROOT/tools/requirements-dev.txt"
fi
"$python" -m pip install --no-deps -e "$ROOT"
if [ "$build_ok" = 0 ]; then "$python" -m pip install 'cmake>=3.24,<5'; fi
if [ "$ninja_ok" = 0 ]; then "$python" -m pip install 'ninja>=1.11,<2'; fi
hash -r
scan
if [ "$ready" != 1 ]; then echo 'Setup incomplete. Resolve the missing items above and rerun setup.' >&2; exit 1; fi
if [ "$esp32" = 1 ]; then
    "$ROOT/build/python/bin/python" "$ROOT/src/micros_tooling/platforms/esp32/bootstrap.py"
fi
echo 'Ready. Create an application with micros new, then follow https://docs.meetmicros.com/site/get-started/.'
echo 'Board toolchains, Docker and contributor-only tools are separate; see the relevant guide.'
