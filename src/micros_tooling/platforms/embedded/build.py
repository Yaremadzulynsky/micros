"""Freestanding native images and shared embedded graph construction."""

import hashlib
import json
from pathlib import Path
import struct
import subprocess
import zlib
from elftools.elf.elffile import ELFFile
from micros_tooling.storage.packages import (
    require,
    build_package,
    read_package,
    admission_plan,
    canonical_schema,
    digest,
)
from micros_tooling.config.configuration import (
    load_project,
    generate_service_headers,
    config_artifacts,
)
from micros_tooling.config.protobuf import RUNTIME, RUNTIME_SOURCES
from micros_tooling.storage.native_image import envelope, ABI_MAJOR, ABI_REVISION

ROOT = Path(__file__).resolve().parents[4]
BANK_BASE, BANK_BYTES, GRAPH_BYTES, SLOT_BYTES, DATA_BYTES = 0x20000, 0x10000, 4096, 0x3C00, 512
SERVICE = struct.Struct("<64s32s7I256s")
GRAPH_HEADER = struct.Struct("<5I32s")


def build_image(service, sources, includes, output, compiler_dir, info, bank):
    output.mkdir(parents=True, exist_ok=True)
    slot = service["slot"]
    code_base = (
        info["bank_base"]
        + bank * info["bank_bytes"]
        + GRAPH_BYTES
        + slot * info["slot_bytes"]
        + 64
    )
    data_base = info["data_base"] + slot * info["data_bytes"]
    flags = [
        *info["compile_flags"],
        "-Os",
        "-ffreestanding",
        "-ffunction-sections",
        "-fdata-sections",
        "-fno-builtin",
        "-fno-common",
        "-fno-stack-protector",
        "-fno-unwind-tables",
        "-fno-asynchronous-unwind-tables",
        "-fno-tree-loop-distribute-patterns",
        "-Wall",
        "-Wextra",
        "-Werror",
    ]
    objects, sections = [], []
    descriptor = service.get("descriptor", "micros_descriptor")
    for index, source in enumerate([*sources, ROOT / "src/sdk/c/src/freestanding.c"]):
        source = Path(source)
        cpp = source.suffix in (".cpp", ".cc", ".cxx")
        compiler = Path(compiler_dir) / (info["compiler_prefix"] + ("g++" if cpp else "gcc"))
        obj = output / f"source{index}.o"
        subprocess.run(
            [
                str(compiler),
                *flags,
                *(
                    ["-std=c++17", "-fno-exceptions", "-fno-rtti", "-fno-threadsafe-statics"]
                    if cpp
                    else ["-std=c17"]
                ),
                *["-I" + str(path) for path in includes],
                *["-D" + value for value in service.get("defines", [])],
                "-c",
                str(source),
                "-o",
                str(obj),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        with obj.open("rb") as stream:
            elf = ELFFile(stream)
            require(
                not any(
                    s["sh_size"]
                    and (
                        s["sh_flags"] & 0x400
                        or s["sh_type"]
                        in ("SHT_INIT_ARRAY", "SHT_FINI_ARRAY", "SHT_PREINIT_ARRAY")
                    )
                    for s in elf.iter_sections()
                ),
                "Service static constructors/TLS are unsupported",
            )
            found = elf.get_section_by_name(".symtab").get_symbol_by_name(descriptor) or []
            sections += [
                elf.get_section(symbol["st_shndx"]).name
                for symbol in found
                if isinstance(symbol["st_shndx"], int)
            ]
        objects.append(obj)
    require(len(sections) == 1, "Expected one native descriptor symbol: " + descriptor)
    linker = output / "service.ld"
    linker.write_text(f"""ENTRY({descriptor})
SECTIONS {{
 .data 0x{data_base:x} : ALIGN(16) {{ KEEP(*({sections[0]})) *(.data .data.*) . = ALIGN(4); }}
 .bss (NOLOAD) : ALIGN(4) {{ *(.bss .bss.*) *(COMMON) . = ALIGN(4); }}
 .text 0x{code_base:x} : ALIGN(4) {{ *(.literal .literal.*) *(.text .text.*) *(.rodata .rodata.*) . = ALIGN(4); }}
 /DISCARD/ : {{ *(.comment) *(.note*) *(.ARM.exidx*) *(.ARM.extab*) *(.eh_frame*) }}
}}
ASSERT(SIZEOF(.text) + SIZEOF(.data) + 64 <= {info['slot_bytes']}, "service flash slot overflow")
ASSERT(SIZEOF(.data) + SIZEOF(.bss) <= {info['data_bytes']}, "service RAM data slot overflow")
""")
    executable = output / "service.elf"
    subprocess.run(
        [
            str(Path(compiler_dir) / (info["compiler_prefix"] + "gcc")),
            *info["link_flags"],
            "-nostdlib",
            "-Wl,--no-undefined",
            "-Wl,--gc-sections",
            "-Wl,-T," + str(linker),
            *map(str, objects),
            "-lgcc",
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    with executable.open("rb") as stream:
        elf = ELFFile(stream)
        require(
            not any(
                s["sh_type"] in ("SHT_REL", "SHT_RELA") and s["sh_size"]
                for s in elf.iter_sections()
            ),
            "Runtime relocations are unsupported",
        )
        require(
            not any(
                s["sh_flags"] & 2 and s["sh_size"] and s.name not in (".text", ".data", ".bss")
                for s in elf.iter_sections()
            ),
            "Unsupported allocated service section",
        )
        text, data = elf.get_section_by_name(".text").data(), bytearray(
            elf.get_section_by_name(".data").data()
        )
        bss = elf.get_section_by_name(".bss")
        symbol = elf.get_section_by_name(".symtab").get_symbol_by_name(descriptor)[0]
        offset = symbol["st_value"] - data_base
        values = list(struct.unpack_from("<12I", data, offset))
        require(
            values[:4] == [48, ABI_MAJOR, ABI_REVISION, info["target"]] and values[7] == 0,
            "Invalid native descriptor",
        )
        values[6] = service["stack_bytes"]
        require(512 <= values[6] <= 4096, "Service stack budget must be 512..4096 bytes")
        struct.pack_into("<12I", data, offset, *values)
    image = envelope(
        info["target"], text, data, bss["sh_size"] if bss else 0, code_base, data_base, offset
    )
    (output / "service.mimg").write_bytes(image)
    return image, dict(
        arena="RAM", arena_bytes=values[4], arena_alignment=values[5], stack_bytes=values[6]
    )


def build(project, info, output, compiler_dir, bank, board=None, overlay=None):
    require(bank in (0, 1), "Invalid bank")
    project, output = Path(project).resolve(), Path(output).resolve()
    recipe = load_project(project, overlay, board)
    require(
        recipe.get("board") and recipe["board"]["profile"] == info["board_profile"],
        "Select the matching board definition",
    )
    generate_service_headers(project, board, recipe)
    packages = []
    for service in recipe["services"]:
        sources = [Path(path) for path in service["sources"]]
        includes = [ROOT / "src/sdk/abi/include", ROOT / "src/sdk/c/include", RUNTIME]
        from micros_tooling.config.artifacts import build_inputs
        generated_sources, generated_includes = build_inputs(service)
        sources.extend(generated_sources)
        includes.extend(generated_includes)
        includes.append(ROOT / 'src/sdk/abi/internal')
        if any(p.name.endswith('.pb.c') for p in generated_sources):
            sources.extend(RUNTIME_SOURCES)
        config = b""
        if "_configuration" in service:
            spec = service["_configuration"]
            _, config = config_artifacts(spec["name"], spec["definition"], spec["values"])
        image, memory = build_image(
            service, sources, includes, output / service["name"], compiler_dir, info, bank
        )
        schemas = {name: Path(path).read_bytes() for name, path in service["schemas"].items()}
        manifest = dict(
            format=1,
            name=service["name"],
            version=service["version"],
            target=info["target"],
            abi=dict(major=ABI_MAJOR, revision=ABI_REVISION),
            image_sha256=digest(image),
            memory=memory,
            capabilities=service["capabilities"],
            channels=service["channels"],
            schemas={name: digest(canonical_schema(data)) for name, data in schemas.items()},
            persistent_data_version=0,
            config=config.hex(),
            board_bindings={key: recipe["board"][key] for key in ("gpio", "recovery_button")},
        )
        require(len(manifest["version"].encode()) < 32, "MKR version string must fit 31 bytes")
        package = build_package(manifest, image, schemas)
        path = output / (service["name"] + ".msp")
        path.write_bytes(package)
        packages.append(read_package(package))
    plan = admission_plan(packages, target=info["target"])
    from micros_tooling.storage.deployment import encode_graph
    bindings = {key: recipe['board'][key] for key in ('gpio', 'recovery_button')}
    slots = {package['manifest']['name']: index for index, package in enumerate(packages)}
    graph = encode_graph(plan, bank, slots, bindings)
    bank_data = bytearray(b"\xff" * info["bank_bytes"])
    bank_data[: len(graph)] = graph
    for index, package in enumerate(packages):
        offset = GRAPH_BYTES + index * info["slot_bytes"]
        bank_data[offset : offset + len(package["image"])] = package["image"]
    (output / "bank.bin").write_bytes(bank_data)
    report = dict(
        bank=bank,
        bank_bytes=info["bank_bytes"],
        base_sha256=info["hash"].hex(),
        graph_sha256=hashlib.sha256(graph + b"".join(packages[slots[s["name"]]]["image"] for s in plan["services"])).hexdigest(),
        plan=plan,
        graph_bytes=len(graph),
        slot_bytes=info["slot_bytes"],
    )
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
