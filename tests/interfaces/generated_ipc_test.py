"""Compile-time port grants, binding dispatch and removal of stale generated APIs."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from micros_tooling.config.configuration import generate_service_headers
from micros_tooling.storage.packages import PackageError
from micros_tooling.config.protobuf import RUNTIME, RUNTIME_SOURCES


class GeneratedIpcTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.project = self.directory / "micros.toml"
        shutil.copyfile(ROOT / "src/sdk/protos/button/v1/button_state.proto", self.directory / "button_state.proto")
        self.write_project()

    def write_project(self, access="subscriptions", key=1, port="button"):
        self.project.write_text(
            '[services.colors]\nmemory = { arena = "RAM" }\nsource = "."\nname = "board.colors"\nversion = "1.0.0"\n'
            '[services.colors.build]\nsources = ["src/button_input.c"]\n'
            '[services.colors.capabilities]\ntimers = 0\ngpio = []\n'
            + (f'[services.colors.{access}.{port}]\nchannel = "button"\n' if access else '')
            + f'[channels.button]\nkey = {key}\nmax_payload = 64\nschema = "button_state.proto"\n'
        )
        generate_service_headers(self.project)

    def compile(self, source, success=True, cpp=False, link=False, extra_sources=()):
        path = self.directory / ("check.cpp" if cpp else "check.c")
        path.write_text(source)
        command = ["c++" if cpp else "cc", "-std=c++17" if cpp else "-std=c17",
                   "-Wall", "-Wextra", "-Werror", "-pedantic-errors",
                   "-I", str(RUNTIME), "-I", str(ROOT / "src/sdk/abi/include"), "-I", str(ROOT / "src/sdk/c/include")]
        if link:
            command += [str(path), str(self.directory / "generated/colors_ipc.c"),
                        *map(str, (self.directory / "generated").glob("*.pb.c")),
                        *map(str, RUNTIME_SOURCES), *map(str, extra_sources), "-o", str(self.directory / "check")]
        else:
            command += ["-fsyntax-only", str(path)]
        result = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, success, result.stderr)
        return result.stderr

    def test_direction_and_raw_api_are_compile_time_errors(self):
        valid = '#include "generated/colors_ipc.h"\nvoid check(void) { (void)&colors_button_read; }\n'
        self.compile(valid)
        self.compile(valid, cpp=True)
        self.compile(valid.replace("_read", "_publish"), success=False)
        self.compile('#include <micros/service.h>\nvoid check(const micros_service_args_t *args) { (void)args->api->ipc_open; }\n', success=False)
        self.compile('#include <micros/service.h>\nvoid check(const micros_service_args_t *args) { (void)args->api->_ipc->ipc_open; }\n', success=False)
        self.write_project(access="publications")
        self.compile(valid, success=False)
        self.compile(valid.replace("_read", "_publish"))

    def test_removing_subscription_breaks_actual_colors_source(self):
        source_directory = self.directory / "src"
        source_directory.mkdir()
        for name in ("button_input.c", "button_input.h"):
            shutil.copyfile(ROOT / "examples/services/colors/src" / name, source_directory / name)
        self.compile('#include "src/button_input.c"\n')
        self.write_project(access=None)
        error = self.compile('#include "src/button_input.c"\n', success=False)
        self.assertIn("colors_button_open", error)
        self.assertNotIn("colors_button_read", (self.directory / "generated/colors_ipc.h").read_text())
        self.assertNotIn("ipc_open", (self.directory / "generated/colors_ipc.c").read_text())

    def test_key_remap_and_access_reach_runtime(self):
        # Kernel-like stub observes dispatch without granting service code raw IPC access.
        stub = '''#include "generated/colors_ipc.h"
#include "PRIVATE_HEADER"
#include <assert.h>
static micros_result_t observe(micros_context_t *context, uint32_t key, uint32_t access, micros_handle_t *handle)
{
    (void)context;
    assert(key == EXPECTED_KEY);
    assert(access == EXPECTED_ACCESS);
    *handle = 42;
    return MICROS_OK;
}
int main(void)
{
    const struct micros_ipc_api ipc = {.ipc_open = observe};
    const micros_api_t api = {._ipc = &ipc};
    const micros_service_args_t args = {.api = &api};
    micros_handle_t handle = 0;
    assert(colors_button_open(&args, &handle) == MICROS_OK);
    assert(handle == 42);
    assert(colors_button_open(0, &handle) == MICROS_ERROR_UNSUPPORTED);
    return 0;
}
'''.replace("PRIVATE_HEADER", str(ROOT / "src/sdk/abi/internal/micros/ipc.h"))
        for access, key, flag in (("subscriptions", 1, "MICROS_IPC_SUBSCRIBE"),
                                  ("subscriptions", 7, "MICROS_IPC_SUBSCRIBE"),
                                  ("publications", 7, "MICROS_IPC_PUBLISH")):
            self.write_project(access=access, key=key)
            self.compile(stub.replace("EXPECTED_KEY", str(key)).replace("EXPECTED_ACCESS", flag), link=True)
            subprocess.run([str(self.directory / "check")], check=True)

    def test_proto_edits_regenerate_types_and_reject_unbounded_fields(self):
        proto = self.directory / "button_state.proto"
        original = proto.read_text()
        header = self.directory / "generated/button_state.pb.h"
        previous_time = header.stat().st_mtime_ns
        generate_service_headers(self.project)
        self.assertEqual(previous_time, header.stat().st_mtime_ns)
        proto.write_text(original.replace("bool pressed = 3;", "bool pressed = 3;\n  uint32 clicks = 5;"))
        generate_service_headers(self.project)
        self.compile('#include "generated/colors_ipc.h"\nvoid check(colors_button_message_t *message) { message->clicks = 3; }\n')
        previous = header.read_bytes()
        proto.write_text(original.replace("bool pressed = 3;", "string label = 3;"))
        with self.assertRaises(PackageError):
            generate_service_headers(self.project)
        self.assertEqual(header.read_bytes(), previous)
        proto.write_text(original.replace('package micros.button.v1;', 'package micros.button.v1;\nimport "nanopb.proto";').replace(
            "bool pressed = 3;", 'string label = 3 [(nanopb).max_size = 8];'))
        generate_service_headers(self.project)
        self.compile('#include "generated/colors_ipc.h"\nvoid check(colors_button_message_t *message) { message->label[0] = 0; }\n')
        self.compile(r'''#include "generated/colors_ipc.h"
#include <assert.h>
int main(void) {
    colors_button_message_t message = {0};
    const uint8_t valid[] = {26, 2, 'o', 'k'};
    const uint8_t invalid[] = {26, 1, 255};
    assert(micros_button_v1_ButtonState_decode(valid, sizeof(valid), &message) == MICROS_OK);
    assert(message.label[0] == 'o');
    assert(micros_button_v1_ButtonState_decode(invalid, sizeof(invalid), &message) == MICROS_ERROR_INVALID_ARGUMENT);
    assert(message.label[0] == 'o');
    return 0;
}
''', link=True)
        subprocess.run([str(self.directory / "check")], check=True)
        self.project.write_text(self.project.read_text().replace("max_payload = 64", "max_payload = 8"))
        with self.assertRaises(PackageError):
            generate_service_headers(self.project)

    def test_typed_publish_read_use_protobuf_and_preserve_output_on_errors(self):
        publisher = self.directory / "publisher"
        publisher.mkdir()
        self.project.write_text(self.project.read_text() +
            '[services.button]\nmemory = { arena = "RAM" }\nsource = "publisher"\nname = "test.button"\nversion = "1.0.0"\n'
            '[services.button.build]\nsources = ["not-built.c"]\n'
            '[services.button.capabilities]\ntimers = 0\ngpio = []\n'
            '[services.button.publications.button]\nchannel = "button"\n')
        generate_service_headers(self.project)
        source = r'''#include "generated/colors_ipc.h"
#include "publisher/generated/button_ipc.h"
#include "PRIVATE_HEADER"
#include <assert.h>
#include <string.h>
static uint8_t wire[64];
static uint32_t wire_bytes;
static micros_result_t read_result;
static micros_result_t publish(micros_context_t *context, micros_handle_t handle,
                               const uint8_t *bytes, uint32_t size)
{
    (void)context; (void)handle;
    assert(size <= sizeof(wire));
    memcpy(wire, bytes, size); wire_bytes = size;
    return MICROS_OK;
}
static micros_result_t read_message(micros_context_t *context, micros_handle_t handle,
    uint8_t *bytes, uint32_t capacity, uint32_t *size, micros_message_info_t *info)
{
    (void)context; (void)handle; (void)info;
    if (read_result) return read_result;
    if (wire_bytes <= capacity) memcpy(bytes, wire, wire_bytes);
    *size = wire_bytes;
    return MICROS_OK;
}
int main(void)
{
    const struct micros_ipc_api ipc = {.ipc_publish = publish, .ipc_read = read_message};
    const micros_api_t api = {._ipc = &ipc};
    const micros_service_args_t args = {.api = &api};
    button_button_message_t sent = {.sequence = 7, .monotonic_us = 123, .pressed = true};
    colors_button_message_t received = {0};
    assert(button_button_publish(&args, 1, &sent) == MICROS_OK);
    const uint8_t expected[] = {8, 7, 16, 123, 24, 1}; /* Protobuf field tags and varints. */
    assert(wire_bytes == sizeof(expected) && !memcmp(wire, expected, sizeof(expected)));
    sent.pressed = false; /* Publication retained bytes, not the caller's struct. */
    assert(colors_button_read(&args, 2, &received) == MICROS_OK);
    assert(received.sequence == 7 && received.monotonic_us == 123 && received.pressed);
    read_result = MICROS_ERROR_MESSAGES_MISSED;
    assert(colors_button_read(&args, 2, &received) == read_result);
    read_result = MICROS_ERROR_EMPTY;
    assert(colors_button_read(&args, 2, &received) == read_result);
    read_result = MICROS_OK;
    wire[0] = 8; wire_bytes = 1; /* Truncated sequence varint. */
    assert(colors_button_read(&args, 2, &received) == MICROS_ERROR_INVALID_ARGUMENT);
    wire_bytes = 65; /* A broken dispatch cannot overrun the typed decoder's buffer. */
    assert(colors_button_read(&args, 2, &received) == MICROS_ERROR_CAPACITY);
    assert(received.sequence == 7 && received.monotonic_us == 123 && received.pressed);
    return 0;
}
'''.replace("PRIVATE_HEADER", str(ROOT / "src/sdk/abi/internal/micros/ipc.h"))
        self.compile(source, link=True, extra_sources=[publisher / "generated/button_ipc.c"])
        subprocess.run([str(self.directory / "check")], check=True)

    def test_invalid_ports_do_not_overwrite_valid_output(self):
        header = self.directory / "generated/colors_ipc.h"
        previous = header.read_bytes()
        for key in (0, 33, True):
            with self.assertRaises((PackageError, ValueError)):
                self.write_project(key=key)
            self.assertEqual(header.read_bytes(), previous)
        with self.assertRaises(PackageError):
            self.write_project(port="not-a-c-name")
        self.write_project()
        self.project.write_text(self.project.read_text() + '\n[services.colors.publications.button]\nchannel = "button"\n')
        with self.assertRaises(PackageError):
            generate_service_headers(self.project)
        self.assertEqual(header.read_bytes(), previous)


if __name__ == "__main__":
    unittest.main()
