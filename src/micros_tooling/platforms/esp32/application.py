"""Build ESP32 applications against an exact resident firmware image."""

import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys

from micros_tooling.storage.packages import (
    ABI_MAJOR,
    ABI_REVISION,
    build_package,
    canonical_schema,
    digest,
    identifier,
    require,
)
from micros_tooling.storage.store import atomic_write
from micros_tooling.config.protobuf import RUNTIME, RUNTIME_SOURCES
from micros_tooling.config.configuration import (
    load_project,
    config_artifacts,
    generate_service_headers,
)

ROOT = Path(__file__).resolve().parents[4]
PINNED_COMPILER = "esp-14.2.0_20251107"


def build_application(project, firmware, output, progress, overlay=None, board=None):
    project, firmware, output = Path(project).resolve(), Path(firmware), Path(output)
    require(
        project.is_file(), f"Application file not found: {project}. Use --project PATH."
    )
    recipe = load_project(project, overlay, board)
    from micros_tooling.config.resources import verify_board_firmware
    verify_board_firmware(recipe.get("board"), firmware)
    generate_service_headers(project, board, recipe)
    require(isinstance(recipe, dict), "Application recipe must resolve to an object.")
    require(
        recipe.get("format") == 1, "Unsupported application recipe format; expected 1."
    )
    services = recipe.get("services", [])
    require(
        isinstance(services, list) and 1 <= len(services) <= 4,
        "Application must contain one to four services.",
    )
    for index, service in enumerate(services, 1):
        required_fields = {"name", "version", "slot", "sources", "capabilities"}
        optional_fields = {
            "defines", "arena", "stack_bytes",
            "descriptor",
            "channels",
            "schemas",
            "persistent_data_version",
            "_configuration",
            "_interface",
            "_commands",
            "_contract",
        }
        require(
            isinstance(service, dict) and required_fields <= service.keys(),
            f"Service {index}: expected name, version, slot, sources and capabilities.",
        )
        require(
            service.keys() <= required_fields | optional_fields,
            f"Service {index}: unrecognized configuration field.",
        )
        require(
            isinstance(service["sources"], list)
            and service["sources"]
            and all(
                isinstance(source, str) and source for source in service["sources"]
            ),
            f"Service {index}: sources must be a nonempty list of paths.",
        )
        definitions = service.get("defines", [])
        require(
            isinstance(definitions, list)
            and all(isinstance(value, str) for value in definitions),
            f"Service {index}: defines must be a list of strings.",
        )
        schemas = service.get("schemas", {})
        require(
            isinstance(schemas, dict)
            and all(isinstance(value, str) for value in schemas.values()),
            f"Service {index}: schemas must map names to file paths.",
        )
    names = [identifier(service["name"], "service name") for service in services]
    slots = [service["slot"] for service in services]
    require(
        len(set(names)) == len(names), "Application contains duplicate service names."
    )
    require(
        all(type(slot) is int and 0 <= slot < 4 for slot in slots)
        and len(set(slots)) == len(slots),
        "Each service needs a distinct slot from 0 to 3.",
    )
    requirements = dict(recipe.get("required_sdkconfig", {}))
    if any(service.get("arena") == "PSRAM" for service in services):
        require("CONFIG_SPIRAM" not in requirements or requirements["CONFIG_SPIRAM"] == "y", "PSRAM arena conflicts with base configuration")
        requirements["CONFIG_SPIRAM"] = "y"
    require(
        isinstance(requirements, dict),
        "required_sdkconfig must map settings to values.",
    )
    if requirements:
        configuration = firmware.with_name("sdkconfig")
        require(
            configuration.is_file(),
            "This application requires the paired base sdkconfig. Add the device with --sdkconfig PATH.",
        )
        settings = dict(
            line.split("=", 1)
            for line in configuration.read_text().splitlines()
            if line.startswith("CONFIG_") and "=" in line
        )
        for key, expected in requirements.items():
            require(
                settings.get(key) == expected,
                f'Paired base must have {key}={expected or "disabled"}.',
            )
    environment = os.environ.copy()
    compiler = shutil.which("xtensa-esp32-elf-gcc")
    if not compiler:
        compiler = (
            Path.home()
            / ".espressif/tools/xtensa-esp-elf"
            / PINNED_COMPILER
            / "xtensa-esp-elf/bin/xtensa-esp32-elf-gcc"
        )
        require(
            compiler.is_file(),
            "ESP32 compiler missing. Install the pinned toolchain using docs/archive/documentation/BUILDING.md.",
        )
        environment["PATH"] = (
            str(compiler.parent) + os.pathsep + environment.get("PATH", "")
        )
    from micros_tooling.platforms.esp32.build_service import load_symbol_addresses

    require(
        "micros_runtime_ipc_api" in load_symbol_addresses(firmware),
        "This build requires ABI 0 revision 5 generated IPC support. The paired base is older; "
        "build a new base for review, then migrate the device before deploying.",
    )
    packages = []
    for service in services:
        name = service["name"]
        progress("build", f'Building {name} {service["version"]}')
        directory = output / name
        directory.mkdir(parents=True, exist_ok=True)
        sources = list(service.get("sources", []))
        from micros_tooling.config.artifacts import build_inputs
        generated_sources, generated_includes = build_inputs(service)
        sources.extend(map(str, generated_sources))
        if any(str(p).endswith('.pb.c') for p in generated_sources):
            sources.extend(map(str, RUNTIME_SOURCES))
        require(sources, f"{name}: specify at least one source file.")
        command = [
            sys.executable,
            str(ROOT / "src/micros_tooling/platforms/esp32/build_service.py"),
            "--firmware",
            str(firmware),
            "--output",
            str(directory),
            "--arena", service["arena"],
            "--stack-bytes", str(service.get("stack_bytes", 4096)),
            "--slot",
            str(service["slot"]),
            "--include-directory", str(RUNTIME),
            "--include-directory", str(ROOT / "src/sdk/abi/internal"),
            "--descriptor-symbol",
            service.get("descriptor", "micros_descriptor"),
        ]
        for generated_directory in generated_includes:
            command += ["--include-directory", str(generated_directory)]
        configuration_payload = b""
        if "_configuration" in service:
            specification = service["_configuration"]
            _, configuration_payload = config_artifacts(
                specification["name"],
                specification["definition"],
                specification["values"],
            )
        for source in sources:
            source = project.parent / source
            require(source.is_file(), f"{name}: source not found: {source}")
            command += ["--source", str(source)]
        for definition in service.get("defines", []):
            command += ["--define", definition]
        # Configuration values are deliberately absent from the executable cache key.
        # Traverse project headers so changing code, types or defaults invalidates the image.
        include_dirs = [
            RUNTIME,
            ROOT / "src/sdk/abi/include",
            ROOT / "src/sdk/abi/internal",
            ROOT / "src/sdk/c/include",
            *generated_includes,
        ]
        pending = [Path(project.parent / source).resolve() for source in sources]
        dependencies = {}
        while pending:
            dependency = pending.pop()
            if str(dependency) in dependencies:
                continue
            content = dependency.read_bytes()
            dependencies[str(dependency)] = digest(content)
            for included in re.findall(
                rb'^\s*#\s*include\s*[<"]([^>"]+)[>"]', content, re.M
            ):
                candidates = [dependency.parent / included.decode()] + [
                    base / included.decode() for base in include_dirs
                ]
                resolved = next(
                    (
                        candidate.resolve()
                        for candidate in candidates
                        if candidate.is_file()
                    ),
                    None,
                )
                if resolved:
                    pending.append(resolved)
        compiler_identity = subprocess.check_output(
            [str(compiler), "--version"], env=environment, text=True
        )
        fingerprint = digest(
            json.dumps(
                dict(
                    command=command,
                    dependencies=dependencies,
                    firmware=digest(firmware.read_bytes()),
                    compiler=compiler_identity,
                    builder=digest(
                        (ROOT / "src/micros_tooling/platforms/esp32/build_service.py").read_bytes()
                    ),
                    packager=digest((ROOT / "src/micros_tooling/storage/native_image.py").read_bytes()),
                ),
                sort_keys=True,
            ).encode()
        )
        cache_file = directory / "executable-cache.json"
        artifacts = [directory / "service.mimg", directory / "report.json"]
        cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
        reusable = cache.get("inputs") == fingerprint and all(
            path.is_file() for path in artifacts
        )
        reusable = reusable and cache.get("outputs") == [
            digest(path.read_bytes()) for path in artifacts
        ]
        if reusable:
            progress("build", f"Reusing executable for {name}; packaging configuration")
        else:
            result = subprocess.run(
                command, env=environment, text=True, capture_output=True
            )
            log = directory / "build.log"
            log.write_text(result.stdout + result.stderr)
            require(
                result.returncode == 0,
                f"{name}: build failed. Compiler output: {log}\n{result.stderr[-2000:]}",
            )
            atomic_write(
                cache_file,
                json.dumps(
                    dict(
                        inputs=fingerprint,
                        outputs=[digest(path.read_bytes()) for path in artifacts],
                    )
                ).encode(),
            )
        image = (directory / "service.mimg").read_bytes()
        schemas = {
            alias: (project.parent / path).read_bytes()
            for alias, path in service.get("schemas", {}).items()
        }
        description = dict(
            format=1,
            name=name,
            version=service["version"],
            target=2,
            abi=dict(major=ABI_MAJOR, revision=ABI_REVISION),
            image_sha256=digest(image),
            memory=json.loads((directory / "report.json").read_text())["memory"],
            capabilities=service["capabilities"],
            channels=service.get("channels", []),
            schemas={
                alias: digest(canonical_schema(data)) for alias, data in schemas.items()
            },
            persistent_data_version=service.get("persistent_data_version", 0),
            build_identity=dict(
                # Source release identity excludes output paths and fixed placement.
                # The image hash still identifies the exact linked artifact.
                source_sha256=digest(json.dumps(dict(
                    dependencies=sorted((os.path.relpath(path, ROOT), value)
                                        for path, value in dependencies.items()
                                        # Wiring is deployment data, while cache inputs still
                                        # include this header so pin changes rebuild the image.
                                        if not (Path(path).parent.name == "generated"
                                                and Path(path).name.endswith(("_resources.h", "_bindings.c")))),
                    sources=[os.path.relpath(path, ROOT) for path in sources if not Path(path).name.endswith("_bindings.c")],
                    defines=service.get("defines", []), descriptor=service.get("descriptor", "micros_descriptor"),
                    compiler=compiler_identity,
                    builder=digest((ROOT / "src/micros_tooling/platforms/esp32/build_service.py").read_bytes()),
                ), sort_keys=True).encode()),
                slot=service["slot"],
            ),
        )
        from micros_tooling.commands.metadata import build as build_commands
        command_metadata = build_commands(service)
        if command_metadata is not None:
            description["commands"] = command_metadata
        from micros_tooling.communication.channel_metadata import build as build_ports
        ports = build_ports(service)
        if ports:
            description["published_ports"] = ports
        if service.get("_interface", {}).get("name") == "bridge":
            description["ipc_bridge"] = True
        if recipe.get("board"):
            description["board_bindings"] = {key: recipe["board"][key] for key in ("gpio", "recovery_button")}
        if configuration_payload:
            description["config"] = configuration_payload.hex()
        atomic_write(
            directory / "manifest.json",
            json.dumps(description, indent=2).encode() + b"\n",
        )
        atomic_write(directory / "config.bin", configuration_payload)
        package = output / (name + ".msp")
        atomic_write(package, build_package(description, image, schemas))
        packages.append(package)
    atomic_write(
        output / "resolved.json", json.dumps(recipe, indent=2).encode() + b"\n"
    )
    return packages
