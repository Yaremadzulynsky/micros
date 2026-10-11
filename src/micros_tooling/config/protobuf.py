"""Pinned Nanopb generation for bounded, self-contained protobuf message contracts."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from micros_tooling.storage.packages import require, digest, canonical_schema

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / "src/third_party/nanopb"
RUNTIME_SOURCES = [RUNTIME / name for name in ("pb_common.c", "pb_encode.c", "pb_decode.c")]


def compile_schema(schema):
    """Read the actual proto with protoc; return generated files, type and descriptor bytes."""
    try:
        import grpc_tools
        import nanopb
        from google.protobuf import descriptor_pb2
        installed = version("nanopb"), version("grpcio-tools")
    except (ImportError, PackageNotFoundError):
        require(False, "Install protobuf tools: python -m pip install -r tools/requirements-dev.txt")
    require(installed == ("0.4.9.1", "1.62.3"),
            "Install the pinned protobuf generators from tools/requirements-dev.txt")
    schema = Path(schema).resolve()
    require(schema.is_file(), f"Protobuf schema not found: {schema}")
    nanopb_protos = Path(nanopb.__file__).parent / "generator/proto"
    google_protos = Path(grpc_tools.__file__).parent / "_proto"
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        descriptor = directory / "schema.pb"
        command = [sys.executable, "-m", "grpc_tools.protoc", "-I" + str(schema.parent),
                   "-I" + str(nanopb_protos), "-I" + str(google_protos),
                   "--include_imports", "--descriptor_set_out=" + str(descriptor), schema.name]
        result = subprocess.run(command, cwd=directory, text=True, capture_output=True)
        require(result.returncode == 0, f"{schema}: protoc failed:\n{result.stderr}")
        descriptor_bytes = descriptor.read_bytes()
        descriptions = descriptor_pb2.FileDescriptorSet.FromString(descriptor_bytes)
        description = next(item for item in descriptions.file if item.name == schema.name)
        require(description.syntax == "proto3", f"{schema}: use proto3")
        require(set(description.dependency) <= {"nanopb.proto"},
                f"{schema}: message imports are not yet supported; keep the wire contract in one proto")
        require(len(description.message_type) == 1,
                f"{schema}: declare one top-level channel message (nested messages are supported)")
        # Nanopb's option import is metadata only; every wire type must belong to this file.
        defined_types = set()
        wire_fields = []

        def collect_types(messages, enums, prefix):
            defined_types.update(prefix + "." + enum.name for enum in enums)
            for message in messages:
                full_name = prefix + "." + message.name
                defined_types.add(full_name)
                wire_fields.extend(message.field)
                collect_types(message.nested_type, message.enum_type, full_name)

        collect_types(description.message_type, description.enum_type,
                      "." + description.package if description.package else "")
        for field in wire_fields:
            require(not field.type_name or field.type_name in defined_types,
                    f"{schema}: imported wire type {field.type_name} is not supported")
        message_name = description.message_type[0].name
        c_type = "_".join(filter(None, [description.package.replace(".", "_"), message_name]))
        # No implicit sidecar .options files: field bounds belong inside the proto.
        # Imported descriptor/option schemas describe the generator, not channel payloads.
        # Keep the full descriptor for reference tests but generate only our wire message.
        generator_description = descriptor_pb2.FileDescriptorSet()
        generator_description.file.add().CopyFrom(description)
        generator_input = directory / "message.pb"
        generator_input.write_bytes(generator_description.SerializeToString())
        options = directory / "empty.options"
        options.write_text("")
        command = [sys.executable, "-m", "nanopb.generator.nanopb_generator", "-q",
                   "-D", str(directory), "-f", str(options), "-s", "type:FT_STATIC", "-x", "nanopb.proto", str(generator_input)]
        result = subprocess.run(command, cwd=directory, text=True, capture_output=True)
        require(result.returncode == 0, f"{schema}: Nanopb requires statically bounded fields:\n{result.stderr}")
        header_name = schema.stem + ".pb.h"
        header = (directory / header_name).read_text()
        size = re.search(r"^#define " + re.escape(c_type) + r"_size\s+(\d+)\s*$", header, re.M)
        require(size is not None and "pb_callback_t" not in header
                and not re.search(r"X\(a,\s*POINTER,", header),
                f"{schema}: message must have a fixed maximum encoded size and no callbacks or pointers")
        require(re.search(r"\b" + re.escape(c_type) + r"\s*;", header),
                f"{schema}: Nanopb type-name overrides are not supported")
        files = {}
        for suffix in (".pb.h", ".pb.c"):
            name = schema.stem + suffix
            files[name] = f"/* Generated from protobuf {schema.name}; edit the proto, not this file. */\n" + (directory / name).read_text()
        codec_name = schema.stem + ".codec.h"
        files[codec_name] = codec_header(header_name, c_type)
        return dict(files=files, type=c_type, codec=codec_name, maximum=int(size.group(1)), descriptor=descriptor_bytes, sha256=digest(canonical_schema(schema.read_bytes())))


def codec_header(header, message_type):
    """Emit typed Nanopb adapters; schema-specific representation comes only from protoc."""
    guard = "MICROS_GENERATED_" + message_type.upper() + "_CODEC_H"
    return f'''/* Generated from protobuf {header}; edit the proto, not this file. */
#ifndef {guard}
#define {guard}
#include "{header}"
#include <micros/service.h>
#include <pb_encode.h>
#include <pb_decode.h>

/** @brief Encode into caller storage; report required bytes before a capacity failure. */
static inline micros_result_t {message_type}_encode(const {message_type} *message,
    uint8_t *buffer, uint32_t capacity, uint32_t *message_bytes)
{{
    if (!message || !message_bytes || (!buffer && capacity))
        return MICROS_ERROR_INVALID_ARGUMENT;
    size_t required = 0;
    if (!pb_get_encoded_size(&required, {message_type}_fields, message) || required > UINT32_MAX)
        return MICROS_ERROR_INVALID_ARGUMENT;
    *message_bytes = (uint32_t)required;
    if (required > capacity)
        return MICROS_ERROR_CAPACITY;
    pb_ostream_t stream = pb_ostream_from_buffer(buffer, capacity);
    return pb_encode(&stream, {message_type}_fields, message)
        ? MICROS_OK : MICROS_ERROR_INVALID_ARGUMENT;
}}

/** @brief Decode protobuf atomically; malformed input leaves the caller's message unchanged. */
static inline micros_result_t {message_type}_decode(const uint8_t *buffer,
    uint32_t message_bytes, {message_type} *message)
{{
    if (!message || (!buffer && message_bytes))
        return MICROS_ERROR_INVALID_ARGUMENT;
    {message_type} decoded = {message_type}_init_default;
    pb_istream_t stream = pb_istream_from_buffer(buffer, message_bytes);
    if (!pb_decode(&stream, {message_type}_fields, &decoded))
        return MICROS_ERROR_INVALID_ARGUMENT;
    *message = decoded;
    return MICROS_OK;
}}
#endif
'''


def compile_text(filename, content):
    """Compile planned protobuf without publishing it in a build directory."""
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / Path(filename).name
        path.write_text(content)
        return compile_schema(path)
