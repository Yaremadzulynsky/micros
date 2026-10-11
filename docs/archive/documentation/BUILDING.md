# Building and validating Micros

<span id="building-and-validating-micros-v1"></span>

Supported developer hosts are macOS ARM64 and Linux ARM64/x86-64. For a short
first result, use [run your first application](../../site/first-application.md). This
page contains full build prerequisites and broader validation procedures.

Embedded targets have separate toolchains and base profiles; use the
[platform index](../../../src/firmware/platforms/README.md) and [target setup](../../site/get-started.md).
ESP32 uses the pinned ESP-IDF/compiler versions below. The native ABI remains
experimental; the [public header](../../../src/sdk/abi/include/micros/service.h) defines the
current revision. Product V1 does not imply a stable ABI major 1.

## Host build and demonstration

Install CMake >=3.24, Ninja, C17/C++17 compilers, and Python >=3.10. The pinned Python requirements include protoc via grpcio-tools and Nanopb; no separate protoc installation is required. From a fresh checkout:

```sh
python3 -m venv build/python
build/python/bin/python -m pip install -r tools/requirements-dev.txt
cmake -S . -B build/host -G Ninja -DCMAKE_BUILD_TYPE=Debug \
  -DPython3_EXECUTABLE="$PWD/build/python/bin/python"
cmake --build build/host
ctest --test-dir build/host --output-on-failure
build/python/bin/python tools/release/demo.py
```

The demo uses the public CLI to install three independent packages, confirm a healthy graph, observe explicit IPC loss, stop/start/restart services, install a C++ replacement, reject a failed replacement through rollback, and reconstruct the good selection after restart. It retains packages, status and logs under a unique `build/v1-demo/run-*` directory. It shuts down its own daemon on completion or failure.

For ASan/UBSan, configure another directory with `-DMICROS_ENABLE_SANITIZERS=ON -DCMAKE_BUILD_TYPE=Debug` and run the same build/CTest commands. Native service images remain freestanding; instrumentation covers the kernel, BSP, parsers and test drivers. Assertions in the release gates require Debug builds.

Docker Desktop can run both Linux profiles from macOS:

```sh
bash tools/release/linux.sh arm64
bash tools/release/linux.sh amd64
```

Each command builds a Debian Bookworm tool image, then runs native checks and the complete demo without network access. On ARM Macs, x86-64 execution uses Docker emulation; it is a functional portability check, not a native x86 performance measurement. The OS packages follow Bookworm updates; exact compiler versions and evidence are recorded in M8. The Docker build context contains only the Dockerfile and pinned Python requirements. The test container mounts the checkout read-only and writes its own ignored output directory.

## ESP32 build

For the compact A/B base variant, see [base-only OTA](BASE_OTA.md). It requires
a one-time physical partition migration; later base updates use management.

Install Python dependencies as above, then install the selected SDK:

```sh
mkdir -p build/toolchains
git clone --branch v5.5.2 --depth 1 --shallow-submodules --recursive \
  https://github.com/espressif/esp-idf.git build/toolchains/esp-idf-v5.5.2
build/toolchains/esp-idf-v5.5.2/install.sh esp32
source build/toolchains/esp-idf-v5.5.2/export.sh
./micros init feather --phase prepare --board boards/feather.toml \
  --relay-credentials .micros/server/enrollments/DEVICE_ID
```

The SDK tag resolves to `30aaf64524299d3bde422ca9a2848090d1bc5d0f`; the builder requires compiler `esp-14.2.0_20251107`. Export the same Python environment used for SDK installation. If multiple Python versions exist, set `IDF_PYTHON_ENV_PATH` to the installed SDK environment before export.

The prepare command builds the current base and application without flashing.
Complete [server enrollment](../../../src/server/README.md) first when the project has a
management server URL. For a direct-only base, clear that URL and omit
`--relay-credentials`. Preparation artifacts live in `.micros/onboarding/NAME/`;
use [ONBOARDING](ONBOARDING.md) for the explicit flash/connect phases and initial deployment.
Each service links separately against exported slot addresses in the paired base ELF.

For a lower-level network build with an existing private management identity, use
`build/python/bin/python micros_tooling/platforms/esp32/build_network.py --board boards/feather.toml`.
Include the enrollment inputs required by the configured server; inspect `--help`
for those options. This builder retains existing SDK configuration. Credentials
and generated firmware remain private.

`tools/release/build_device.py` and the `build/device-demo`, `build/device-cpp`,
failure and LED-update artifacts belong to the historical release harness. The
wrapper now defaults to `tests/fixtures/release-board.toml` (the historical two-line
Feather mapping), independently of editable application settings. Pass `--board PATH`
to select another compatible button/LED map; the builder derives logical line IDs
and puts the same bindings in its packages. `--network` uses the fixture project,
with optional `--relay-credentials` for server enrollment. Hardware scripts still
need review before use with a different map; this does not revalidate old measurements.

## Historical release hardware validation

The commands in this section target the release harness paths and graph fixtures,
not the guided onboarding artifact layout. They are preserved for reproduction,
not claimed as verified against the current base. For current hardware work, follow
[ONBOARDING](ONBOARDING.md) and the dated [resource insights validation](reviews/resource-insights.md).

Identify the current serial port. The development board was `/dev/cu.usbserial-564E0535011`. Save any firmware you need before physically replacing it; this project's original board backup remains locally under `build/backups`.

```sh
idf.py -C platforms/esp32/runtime -B "$PWD/build/esp32-runtime" -p PORT -b 115200 flash
build/python/bin/python tests/hardware/v1.py --port PORT
build/python/bin/python tests/hardware/activation.py --port PORT --output build/m8-activation
```

The V1 suite prepares the new base's inactive service bank, runs all four C/C++ services, checks stable stopped heap after warmup, and verifies boot reconstruction. The activation suite resets at twelve storage/commit/boot boundaries and checks failed-start rollback. These are software resets at instrumented write boundaries, not analog power-disconnection tests. Both scripts mutate only the service store and selection after the separate explicit flash command.

With the network profile already provisioned and the V1 suite completed:

```sh
build/python/bin/python tests/hardware/remote.py --host DEVICE_IP --output build/m8-remote
build/python/bin/python tools/cli/micros_remote.py --host DEVICE_IP status
build/python/bin/python tools/cli/micros_remote.py --host DEVICE_IP logs
```

Run each hardware suite serially. Opening the USB adapter can reset the MCU. The remote suite ends with three healthy services; rerun the V1 suite to leave all four running. The historical M1/M5 hardware harnesses target their historical firmware/storage layouts; use the above suites for V1.

Hold the user button while resetting to enter base-owned physical recovery. Release it, inspect serial status, stage an inactive graph, issue `RESUME`, then activate. The V1 suite performs RESUME explicitly as part of physical development. Remote clients cannot clear recovery. See [M6](milestones/M6.md) for exact journal and rollback behavior.

## Local package management

`tools/cli/microsctl.py --store DIRECTORY` provides `package`, `inspect`, `install`, `list`, `configure`, `plan`, `activate`, `boot`, `status`, `logs`, `start NAME`, `stop NAME`, `restart NAME`, and `shutdown`. `configure` stages desired enablement while stopped; `activate` starts a transactional trial. `boot` reconstructs the journal-selected good graph when one exists. Stop/start changes residency; installed packages and next-boot selections are separate.

Use `tools/packaging/demo_packages.py` to generate editable manifest examples. The [SDK quickstart](SDK.md), [package contract](architecture/decisions/0007-service-packages.md), and [V1 feature/resource report](V1.md) describe the supported scope.
