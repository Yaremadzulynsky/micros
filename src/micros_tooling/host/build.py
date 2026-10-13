"""Compile external applications for the existing native host loader."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from micros_tooling.config.configuration import load_project, generate_service_headers, config_artifacts
from micros_tooling.config.artifacts import build_inputs
from micros_tooling.config.protobuf import RUNTIME, RUNTIME_SOURCES
from micros_tooling.storage.native_image import NATIVE_HOST_TARGET, envelope
from micros_tooling.storage.packages import ABI_MAJOR, ABI_REVISION, build_package, canonical_schema, digest, require
from micros_tooling.storage.store import Store, atomic_write
from micros_tooling.host.native_process import NativeRuntime

ROOT = Path(__file__).resolve().parents[3]


def run(command):
    result = subprocess.run(list(map(str, command)), text=True, capture_output=True)
    require(result.returncode == 0, 'Host build failed:\n' + result.stdout + result.stderr)


def runtime_binary():
    directory = ROOT / 'build/host'
    run(['cmake', '-S', ROOT, '-B', directory, '-DCMAKE_BUILD_TYPE=Debug',
         '-DPython3_EXECUTABLE=' + sys.executable])
    run(['cmake', '--build', directory, '--target', 'micros-control', '-j', '2'])
    return directory / 'micros-control'


def build(project, output, runtime):
    project, output = Path(project).resolve(), Path(output).resolve()
    recipe = load_project(project)
    require(not recipe.get('board'), 'Host applications use host.toml without [board] or [unit]; GPIO is not supported by this workflow.')
    require(not recipe.get('required_sdkconfig'), 'Host applications cannot require ESP32 SDK configuration.')
    require(1 <= len(recipe['services']) <= 4, 'Host application must contain one to four services.')
    require(all(s['arena'] == 'RAM' and not s['capabilities']['gpio'] for s in recipe['services']),
            'Host services require RAM and no physical GPIO.')
    generate_service_headers(project, recipe=recipe)
    output.mkdir(parents=True, exist_ok=True)
    packages = []
    compiler_macros = {}
    for service in recipe['services']:
        directory = output / service['name']
        directory.mkdir(parents=True, exist_ok=True)
        generated, includes = build_inputs(service)
        sources = [Path(s) for s in service['sources']] + generated
        if any(s.name.endswith('.pb.c') for s in sources):
            sources += list(RUNTIME_SOURCES)
        if sys.platform == 'linux':
            sources.append(ROOT/'src/sdk/c/src/freestanding.c')
        includes += [ROOT/'src/sdk/abi/include', ROOT/'src/sdk/abi/internal', ROOT/'src/sdk/c/include', RUNTIME]
        objects = []
        for index, source in enumerate(dict.fromkeys(sources)):
            cpp = source.suffix in ('.cpp', '.cc', '.cxx')
            compiler = os.environ.get('CXX' if cpp else 'CC', 'c++' if cpp else 'cc')
            obj = directory / f'{index}.o'
            command = [compiler, '-std=c++17' if cpp else '-std=c17', '-fPIC', '-ffreestanding',
                       '-fno-builtin', '-fno-stack-protector', '-DMICROS_SERVICE_TARGET=MICROS_BUILD_TARGET', '-c', source, '-o', obj]
            if sys.platform == 'linux':
                if compiler not in compiler_macros:
                    compiler_macros[compiler] = subprocess.check_output(
                        [compiler, '-dM', '-E', '-'], input=b'')
                macros = compiler_macros[compiler]
                if b'__GNUC__' in macros and b'__clang__' not in macros:
                    command += ['-fno-tree-loop-distribute-patterns']
            if cpp: command += ['-fno-exceptions', '-fno-rtti', '-fno-threadsafe-statics']
            for include in includes: command += ['-I', include]
            for define in service.get('defines', []): command += ['-D' + define]
            run(command)
            objects.append(obj)
        library = directory / ('service.dylib' if sys.platform == 'darwin' else 'service.so')
        # Match the established CMake Linux service profile: no CRT constructors,
        # implicit libraries or unresolved imports; bind our freestanding helpers locally.
        link_flags = ['-dynamiclib'] if sys.platform == 'darwin' else [
            '-shared', '-nostdlib', '-Wl,-Bsymbolic', '-Wl,--no-undefined']
        run([os.environ.get('CC', 'cc'), *link_flags, *objects, '-o', library])
        image = envelope(NATIVE_HOST_TARGET, library.read_bytes())
        image_path = directory / 'service.mimg'
        atomic_write(image_path, image)
        # Admission loads the image and reads its descriptor, without running lifecycle hooks.
        # Reuse the native loader rather than executing a second, less restrictive loader.
        with tempfile.TemporaryDirectory(dir=output, prefix='inspect-') as temporary:
            probe = NativeRuntime(Store(temporary), runtime, dict(services=[], channels=[]))
            try:
                instance = probe.command(f'LOAD {str(image_path).encode().hex()} 0 0 0 0 0')['instance']
                status = probe.command(f'STATUS {instance}')
                probe.command(f'UNLOAD {instance}')
            except ValueError as error:
                raise ValueError(f"{service['name']}: native admission failed for {image_path}: {error}") from error
            finally:
                probe.close()
        memory = {key: status[key] for key in ('arena_bytes', 'arena_alignment', 'stack_bytes')}
        require(memory['stack_bytes'] == service['stack_bytes'],
                f"{service['name']}: declared stack_bytes differs from native descriptor")
        schemas = {name: Path(path).read_bytes() for name, path in service.get('schemas', {}).items()}
        manifest = dict(format=1, name=service['name'], version=service['version'],
                        target=NATIVE_HOST_TARGET, abi=dict(major=ABI_MAJOR, revision=ABI_REVISION),
                        image_sha256=digest(image), memory=memory, capabilities=service['capabilities'],
                        channels=service.get('channels', []),
                        schemas={k: digest(canonical_schema(v)) for k,v in schemas.items()}, persistent_data_version=0)
        if '_configuration' in service:
            spec = service['_configuration']
            manifest['config'] = config_artifacts(spec['name'], spec['definition'], spec['values'])[1].hex()
        from micros_tooling.commands.metadata import build as command_metadata
        from micros_tooling.communication.channel_metadata import build as port_metadata
        commands, ports = command_metadata(service), port_metadata(service)
        if commands: manifest['commands'] = commands
        if ports: manifest['published_ports'] = ports
        if service.get('_interface', {}).get('name') == 'bridge': manifest['ipc_bridge'] = True
        package = output / (service['name'] + '.msp')
        atomic_write(package, build_package(manifest, image, schemas))
        atomic_write(directory/'manifest.json', json.dumps(manifest, indent=2).encode())
        packages.append(package)
    return packages
