#!/usr/bin/env bash
# Build an isolated Linux developer tool image, then test and demonstrate actual native services.
set -euo pipefail
cd "$(dirname "$0")/../.."
architecture="${1:-arm64}"
case "$architecture" in arm64|amd64) ;; *) echo 'Use arm64 or amd64' >&2; exit 1;; esac
image="micros-linux-v1:$architecture"
output="$PWD/build/linux-$architecture"
mkdir -p "$output"
# Only the Dockerfile and requirements enter the build context, never local credentials.
context=$(mktemp -d "$PWD/build/linux-context.XXXXXX")
trap 'rm -rf "$context"' EXIT
mkdir -p "$context/tools"
cp tools/release/Dockerfile.linux "$context/Dockerfile"
cp tools/requirements-dev.txt "$context/tools/requirements-dev.txt"
docker build --platform "linux/$architecture" -t "$image" "$context"
docker run --rm --platform "linux/$architecture" --network=none \
    -v "$PWD:/source:ro" -v "$output:/output" "$image" /bin/bash -c '
set -e
cmake -S /source -B /output -G Ninja -DCMAKE_BUILD_TYPE=Debug -DPython3_EXECUTABLE=/opt/micros-python/bin/python
cmake --build /output
ctest --test-dir /output --output-on-failure
/opt/micros-python/bin/python /source/tools/release/demo.py --build /output --output /output/demo
'
