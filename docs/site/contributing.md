---
title: Contributor checks
hide:
  - toc
---

<span class="docs-editorial"></span>

Reference · Contributor checks
{: .arch-eyebrow}

# Contributor checks

## Set up and test

Install Git, CMake 3.24+, Ninja, C17/C++17 compilers and a Python version supported
by [pyproject.toml](../../pyproject.toml). Run from the repository root:

```sh
./micros setup
cmake -S . -B build/host -G Ninja -DCMAKE_BUILD_TYPE=Debug \
  -DPython3_EXECUTABLE="$PWD/build/python/bin/python"
cmake --build build/host
ctest --test-dir build/host --output-on-failure
```

The host suite needs no board or operator credentials. The
[host CI workflow](../../.github/workflows/host.yml) defines the tested operating
systems and tool versions, and also checks new-application generation, composition
and tests. Install Node.js to include the browser-free console checks locally;
they need no npm packages or browser. Hardware tests remain explicit operations.

Add `-R TEST_NAME` to CTest for a focused run. Failure details are in
`build/host/Testing/Temporary/LastTest.log`; the [test index](../../tests/README.md)
locates checks. Console development lives with the [server source](../../src/server/README.md).

## Check documentation

After setup:

```sh
build/python/bin/python -m pip install -r tools/docs/requirements.txt
build/python/bin/python -m mkdocs build --strict
```

The build checks repository entry-point links as well as published pages.
Source links resolve to repository files through `tools/docs/hooks.py`.
Published pages cannot link into archived documentation. Check changed journeys,
section links, search and a narrow viewport when their presentation changes.

Give each fact one authoritative home. Link to CLI help, validators, and working
examples for exact contracts; avoid copying flag/schema catalogs. Keep the
homepage's illustrative greenhouse distinct from executable examples. Historical
[preview evidence](preview-evidence.md) stays dated rather than implying current
coverage. Locate implementation ownership in the [repository map](../../README.md#repository-map).

## Submit a change

Use `service.toml` contracts and unit TOML. Keep developer-owned services and
deployment declarations in independent application projects. Include relevant
regression coverage and explain changed behavior, validation and hardware limits.
Do not commit generated output, device credentials, private base artifacts or
operational history; preserve unrelated changes and existing recovery state.

Report a reproducible issue with SDK revision, OS/Python version, target and
sanitized command output. Hardware reports also need base/release identities,
expected behavior and observed behavior. Never post tokens or private ELF files.
