"""Configuration schema validation, payload delivery, isolation and package identity."""

import copy
import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
from micros_tooling.config.configuration import (
    config_artifacts,
    generate_service_headers,
    load_project,
    read_toml,
)
from micros_tooling.storage.packages import build_package, read_package, PackageError
from micros_tooling.host.native_process import NativeRuntime
from micros_tooling.storage.store import Store
from micros_tooling.storage.workspace import Workspace
from tools.packaging.demo_packages import manifest

FIXTURE = ROOT / "tests/fixtures/configuration/micros.toml"
BOARD = FIXTURE.parent / "board.toml"
BUILD = Path(sys.argv.pop(1)).resolve()
DEFINITION = {
    "fields": read_toml(FIXTURE)["services"]["colors"]["config_schema"]
}


class ConfigurationTests(unittest.TestCase):
    def test_stack_budget_defaults_bounds_and_state_ownership(self):
        real_read = read_toml
        def project_with(memory):
            root = copy.deepcopy(real_read(FIXTURE))
            root["services"]["colors"]["memory"] = memory
            def read(path):
                return root if Path(path).resolve() == FIXTURE.resolve() else real_read(path)
            with patch("micros_tooling.config.configuration.read_toml", side_effect=read):
                return load_project(FIXTURE, board=BOARD)
        for memory, expected in [(dict(arena="RAM"), 4096),
                                 (dict(arena="RAM", stack_bytes=8192), 8192),
                                 *[(dict(arena="RAM", stack_bytes=n), n) for n in (1, 1024, 2048, 4095)]]:
            recipe = project_with(memory)
            service = next(s for s in recipe["services"] if s["name"] == "board.colors")
            self.assertEqual(service["stack_bytes"], expected)
        for value in (0, -1, 16385, True, "8192"):
            with self.subTest(value=value), self.assertRaises(PackageError):
                project_with(dict(arena="RAM", stack_bytes=value))
        with self.assertRaises(PackageError):
            project_with(dict(arena="RAM", arena_bytes=512))

    def test_release_builder_selects_an_explicit_fixture_board(self):
        import runpy
        from tools.packaging.device_demo import fixture_board
        release_board = ROOT / "tests/fixtures/release-board.toml"
        _, lines, _ = fixture_board(release_board)
        self.assertEqual(lines["red_led"]["line"], 0)
        self.assertEqual(lines["user_button"]["line"], 1)
        with tempfile.TemporaryDirectory() as temporary:
            no_controls = Path(temporary) / "board.toml"
            no_controls.write_text('[board]\nprofile="no_controls"\nflash_mb=4\n[board.gpio]\n')
            with self.assertRaisesRegex(PackageError, "requires user_button"):
                fixture_board(no_controls)
        for flags in ([], ["--network"]):
            with self.subTest(flags=flags), patch.object(sys, "argv", ["build_device.py", *flags]),\
                    patch("subprocess.run") as run, patch("micros_tooling.storage.store.atomic_write"):
                runpy.run_path(str(ROOT / "tools/release/build_device.py"), run_name="__main__")
                calls = [call.args[0] for call in run.call_args_list]
                self.assertTrue(any(str(release_board) in str(command) for command in calls))
                self.assertTrue(any("device_demo.py" in str(command) and "--board" in command for command in calls))
                self.assertFalse(any("flash" in command for command in calls))

    def test_no_controls_board_has_no_gpio_or_boot_button_and_fits_flash(self):
        from micros_tooling.config.resources import board_definition, board_header, board_partitions

        # The user-editable board file is not a test fixture.
        board = board_definition(dict(profile="no_controls", flash_mb=4, gpio={}))
        self.assertEqual(board["gpio"], [])
        self.assertIsNone(board["recovery_button"])
        self.assertEqual(board["flash_mb"], 4)
        header = board_header(board)
        self.assertIn("MICROS_RUNTIME_GPIO_CAPACITY 4u", header)
        self.assertIn("MICROS_BOARD_HAS_RECOVERY_BUTTON 0", header)
        for line in board_partitions(board).splitlines():
            if line.startswith("#"):
                continue
            fields = line.split(",")
            self.assertLessEqual(int(fields[3], 0) + int(fields[4], 0), 4 * 1024 * 1024)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "board.toml"
            path.write_text('[board]\nprofile="no_controls"\nflash_mb=4\n[board.gpio]\n')
            with self.assertRaisesRegex(PackageError, "has no GPIO resource"):
                load_project(FIXTURE, board=path)

    def test_deployment_bindings_reject_reserved_duplicate_and_invalid_pins(self):
        from micros_tooling.config.resources import validate_bindings
        valid = dict(gpio=[dict(name="output", line=0, pin=25, direction="output")], recovery_button=None)
        self.assertEqual(validate_bindings(valid), valid)
        # GPIO20 is valid in the IDF mask and exposed as SCL on Feather V2.
        # GPIO24 is absent; package-specific exposure belongs to board metadata.
        for pin in (1, 3, 6, 24, 34, 40, -1):
            bad = copy.deepcopy(valid)
            bad["gpio"][0]["pin"] = pin
            with self.subTest(pin=pin), self.assertRaises(PackageError):
                validate_bindings(bad)
        bad = copy.deepcopy(valid)
        bad["recovery_button"] = "output"
        with self.assertRaises(PackageError):
            validate_bindings(bad)
        bad = copy.deepcopy(valid)
        bad["gpio"].append(dict(name="second", line=1, pin=25, direction="output"))
        with self.assertRaises(PackageError):
            validate_bindings(bad)

    def test_one_application_selects_different_saved_board_definitions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "micros.toml"
            project.write_text('[services.example]\nmemory = { arena = "RAM" }\nsource = "."\nname = "test.board"\nversion = "1.0.0"\n'
                               '[services.example.build]\nsources = ["service.c"]\n'
                               '[services.example.capabilities]\ntimers = 0\ngpio = ["button"]\n')
            boards = root / "boards"
            boards.mkdir()
            for name, pin in (("first", 38), ("second", 35)):
                (boards / (name + ".toml")).write_text(
                    f'[board]\nprofile = "{name}"\nrecovery_button = "button"\n'
                    f'[board.gpio.button]\npin = {pin}\ndirection = "input"\n')
            with self.assertRaisesRegex(PackageError, "Multiple board definitions"):
                load_project(project)
            first = load_project(project, board=boards / "first.toml")
            second = load_project(project, board=boards / "second.toml")
            self.assertNotEqual(first["board"]["sha256"], second["board"]["sha256"])
            self.assertEqual(first["services"][0]["capabilities"], second["services"][0]["capabilities"])
            state = Workspace(root / "state")
            state.write("devices.json", dict(default="other", devices=dict(other=dict(board="board.toml"))))
            saved = state.root / "devices/other/board.toml"
            saved.parent.mkdir(parents=True)
            saved.write_bytes((boards / "second.toml").read_bytes())
            result = subprocess.run([sys.executable, str(ROOT / "tools/micros.py"), "generate",
                                     "--project", str(project), "--json"],
                                    env=dict(os.environ, MICROS_STATE_DIR=str(state.root)),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("GPIO35", (root / "generated/example_resources.h").read_text())

    def test_board_definition_and_embedded_fingerprint(self):
        from micros_tooling.config.resources import board_definition, board_header, verify_board_firmware

        definition = dict(profile="test", recovery_button="user_button", gpio=dict(
            user_button=dict(pin=38, direction="input"),
            red_led=dict(pin=13, direction="output")))
        board = board_definition(definition)
        reordered = copy.deepcopy(definition)
        reordered["gpio"] = dict(reversed(list(reordered["gpio"].items())))
        self.assertEqual(board, board_definition(reordered))
        self.assertIn("{13, 1}, {38, 0}", board_header(board))
        for change in (dict(pin=13, direction="input"), dict(pin=38, direction="output"),
                       dict(pin=40, direction="input"), dict(pin=6, direction="input")):
            invalid = copy.deepcopy(definition)
            invalid["gpio"]["user_button"] = change
            with self.assertRaises(PackageError):
                board_definition(invalid)
        # Build an ELF with the actual Xtensa compiler; no board connection is needed.
        compiler = Path.home() / ".espressif/tools/xtensa-esp-elf/esp-14.2.0_20251107/xtensa-esp-elf/bin/xtensa-esp32-elf-gcc"
        if not compiler.exists():
            self.skipTest("Xtensa compiler unavailable for ELF fingerprint check")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "board.c"
            source.write_text('const char micros_board_config_sha256[] = "' + board["sha256"] + '";\n')
            firmware = root / "board.o"
            subprocess.run([str(compiler), "-c", str(source), "-o", str(firmware)], check=True, capture_output=True)
            verify_board_firmware(board, firmware)
            changed = copy.deepcopy(definition)
            changed["gpio"]["red_led"]["pin"] = 12
            with self.assertRaisesRegex(PackageError, "differs from the paired base"):
                verify_board_firmware(board_definition(changed), firmware)
            source.write_text("int unrelated;\n")
            subprocess.run([str(compiler), "-c", str(source), "-o", str(firmware)], check=True, capture_output=True)
            with self.assertRaisesRegex(PackageError, "no generated board definition"):
                verify_board_firmware(board, firmware)

    def test_named_gpio_grants_generate_only_allowed_operations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "micros.toml"
            declaration = ('[board]\nprofile = "test"\n'
                           '[board.gpio.red_led]\npin = 13\ndirection = "output"\n'
                           '[board.gpio.user_button]\npin = 38\ndirection = "input"\n'
                           '[services.example]\nmemory = { arena = "RAM" }\nsource = "."\nname = "test.gpio"\nversion = "1.0.0"\n'
                           '[services.example.build]\nsources = ["service.c"]\n'
                           '[services.example.capabilities]\ntimers = 0\ngpio = ["user_button"]\n')
            board_text, declaration = declaration.split('[services.example]', 1)
            declaration = '[services.example]' + declaration
            (root / 'boards').mkdir()
            (root / 'boards/test.toml').write_text(board_text)
            project.write_text(declaration)
            self.assertEqual(load_project(project)["services"][0]["capabilities"],
                             dict(timers=0, gpio=[1], handles=1))
            generate_service_headers(project)
            source = root / "service.c"
            source.write_text('#include "generated/example_resources.h"\n'
                              'micros_result_t open_button(const micros_service_args_t *args, micros_handle_t *h) '
                              '{ return example_user_button_open(args, h); }\n')
            command = ["cc", "-std=c11", "-Werror=implicit-function-declaration", "-fsyntax-only",
                       "-I", str(ROOT / "src/sdk/abi/include"), str(source)]
            subprocess.run(command, check=True, capture_output=True)
            project.write_text(declaration.replace('["user_button"]', '[]'))
            generate_service_headers(project)
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            for invalid in ('[1]', '["GPIO38"]', '["user_button", "user_button"]'):
                project.write_text(declaration.replace('["user_button"]', invalid))
                with self.assertRaises(PackageError):
                    load_project(project)

    def test_handle_budget_is_derived_from_declared_resources(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "micros.toml"
            (project.parent / "boards").mkdir()
            (project.parent / "boards/feather.toml").write_bytes((BOARD).read_bytes())
            original = (FIXTURE).read_text()
            project.write_text(original)
            services = load_project(project)["services"]
            self.assertEqual([service["capabilities"]["handles"] for service in services],
                             [3, 1, 3, 0])
            # Two timers plus GPIO and one publication require four handles.
            project.write_text(original.replace("timers = 1", "timers = 2", 1))
            self.assertEqual(load_project(project)["services"][0]["capabilities"]["handles"], 4)
            project.write_text(original.replace("timers = 1", "timers = 8", 1))
            with self.assertRaisesRegex(PackageError, "need 10 handles; per-service limit is 8"):
                load_project(project)
            project.write_text(original.replace("timers = 1", "timers = 1\nhandles = 3", 1))
            with self.assertRaisesRegex(PackageError, "remove capabilities.handles"):
                load_project(project)

    def package(self, brightness, name="config.colors", corrupt=False):
        image = (BUILD / "configured.mimg").read_bytes()
        _, payload = config_artifacts("colors", DEFINITION, {"brightness": brightness})
        if corrupt:
            payload = b"\xff" + payload[1:]
        description = manifest(name, "subscribe", image, b"")
        description.update(
            channels=[],
            schemas={},
            memory=dict(arena_bytes=8, arena_alignment=4, stack_bytes=4096),
            capabilities=dict(handles=0, timers=0, gpio=[]),
            config=payload.hex(),
        )
        return build_package(description, image, {})

    def test_configuration_and_contract_changes_have_distinct_content_hashes(self):
        previous = read_package(self.package(2))
        configured = read_package(self.package(7))
        self.assertEqual(previous["manifest"]["version"], configured["manifest"]["version"])
        self.assertEqual(previous["image"], configured["image"])
        self.assertNotEqual(previous["sha256"], configured["sha256"])
        changed = copy.deepcopy(configured["manifest"])
        changed["memory"]["arena_bytes"] = 16
        contracted = read_package(build_package(changed, configured["image"], {}))
        self.assertEqual(configured["manifest"]["version"], contracted["manifest"]["version"])
        self.assertNotEqual(configured["sha256"], contracted["sha256"])

    def test_native_decoder_defaults_bounds_and_atomic_output(self):
        import ctypes
        import subprocess

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            header, payload = config_artifacts("colors", DEFINITION, {"brightness": 7})
            (directory / "colors_config.h").write_text(header)
            (directory / "decode.c").write_text(
                '#include "colors_config.h"\n'
                "int decode(const uint8_t *data, uint32_t bytes, colors_config_t *out) "
                "{ return colors_config_decode(data, bytes, out); }\n"
            )
            subprocess.run(
                [
                    "cc",
                    "-shared",
                    "-fPIC",
                    "-std=c17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-I",
                    str(ROOT / "src/sdk/abi/include"),
                    str(directory / "decode.c"),
                    "-o",
                    str(directory / "decode.so"),
                ],
                check=True,
            )
            subprocess.run(
                [
                    "c++",
                    "-x",
                    "c++",
                    "-std=c++17",
                    "-pedantic-errors",
                    "-fsyntax-only",
                    "-I",
                    str(ROOT / "src/sdk/abi/include"),
                    str(directory / "decode.c"),
                ],
                check=True,
            )
            library = ctypes.CDLL(str(directory / "decode.so"))
            output = (ctypes.c_uint32 * 2)(99, 99)
            library.decode.argtypes = [
                ctypes.c_char_p,
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_uint32),
            ]
            self.assertEqual(library.decode(None, 0, output), 0)
            self.assertEqual(list(output), [1, 0])
            self.assertEqual(library.decode(payload, len(payload), output), 0)
            self.assertEqual(list(output), [7, 0])
            malformed = [
                payload[:-1],
                payload + b"\0",
                b"\xff" + payload[1:],
                payload[:8] + (256).to_bytes(4, "little") + payload[12:],
                payload[:12] + (8).to_bytes(4, "little"),
            ]
            for data in malformed:
                self.assertNotEqual(library.decode(data, len(data), output), 0)
                self.assertEqual(list(output), [7, 0])

    def test_generate_command_without_device_or_firmware(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = root / "service"
            service.mkdir()
            project = root / "micros.toml"
            project.write_text(
                '[services.example]\nmemory = { arena = "RAM" }\nsource = "service"\nname = "test.service"\nversion = "1.0.0"\n'
                '[services.example.build]\nsources = ["not-built.c"]\n'
                '[services.example.capabilities]\ntimers = 0\ngpio = []\n'
                '[services.example.config_schema.interval_ms]\n'
                'type = "uint32"\ndefault = 20\nmin = 1\nmax = 1000\n'
            )
            environment = dict(os.environ, MICROS_STATE_DIR=str(root / "no-devices"))
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/micros.py"),
                    "generate",
                    "--project",
                    str(project),
                    "--json",
                ],
                env=environment,
                check=True,
                text=True,
                capture_output=True,
            )
            header = service / "generated/example_config.h"
            self.assertEqual(
                json.loads(result.stdout)["headers"],
                [str(header.resolve()), str((service / "generated/example_ipc.h").resolve()), str((service / "generated/example_resources.h").resolve())]
            )
            self.assertIn("example_config_t", header.read_text())
            self.assertFalse((root / "no-devices").exists())
            previous_time = header.stat().st_mtime_ns
            generate_service_headers(project)
            self.assertEqual(header.stat().st_mtime_ns, previous_time)
            project.write_text(
                project.read_text().replace("default = 20", "default = 30")
            )
            generate_service_headers(project)
            self.assertIn("UINT32_C(30)", header.read_text())
            user_header = header.parent / "user_config.h"
            user_header.write_text("/* Maintained by a person. */\n")
            project.write_text(
                project.read_text().replace("services.example", "services.renamed")
            )
            generate_service_headers(project)
            self.assertFalse(header.exists())
            self.assertTrue((service / "generated/renamed_config.h").exists())
            self.assertTrue(user_header.exists())
            (service / "generated/renamed_config.h").write_text("/* Handwritten header. */\n")
            with self.assertRaises(PackageError):
                generate_service_headers(project)

    def test_empty_configuration_tables_generate_no_config_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "micros.toml"
            project.write_text(
                '[services.example]\nmemory = { arena = "RAM" }\nsource = "."\nname = "test.service"\n'
                'version = "1.0.0"\nenabled = true\n'
                '[services.example.config]\n[services.example.config_schema]\n'
                '[services.example.build]\nsources = []\ndefines = []\n'
                'descriptor = "descriptor"\n'
                '[services.example.capabilities]\ntimers = 0\ngpio = []\n'
                '[services.example.subscriptions]\n[services.example.publications]\n'
            )
            service = load_project(project)["services"][0]
            self.assertNotIn("_configuration", service)
            self.assertEqual(service["channels"], [])
            self.assertEqual(generate_service_headers(project), [project.parent.resolve() / "generated/example_ipc.h", project.parent.resolve() / "generated/example_resources.h"])
            self.assertFalse((project.parent / "generated/example_config.h").exists())
            project.write_text(project.read_text().replace(
                '[services.example.config]\n',
                '[services.example.config]\nundeclared = 1\n',
            ))
            with self.assertRaises(PackageError):
                load_project(project)

    def test_values_do_not_change_generated_header(self):
        first, a = config_artifacts("colors", DEFINITION, {"brightness": 2})
        second, b = config_artifacts("colors", DEFINITION, {"brightness": 7})
        self.assertEqual(first, second)
        self.assertNotEqual(a, b)
        for value in (-1, 256, True, "2"):
            with self.assertRaises(PackageError):
                config_artifacts("colors", DEFINITION, {"brightness": value})
        with self.assertRaises(PackageError):
            config_artifacts("colors", DEFINITION, {"initial_color": "purple"})
        with self.assertRaises(PackageError):
            config_artifacts("colors", DEFINITION, {"typo": 2})

    def test_overlay_precedence_and_unknown_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            overlay = Path(temporary) / "overlay.toml"
            overlay.write_text("[services.colors.config]\nbrightness = 7\n")
            services = load_project(FIXTURE, overlay, BOARD)["services"]
            spec = next(
                s["_configuration"] for s in services if s["name"] == "board.colors"
            )
            self.assertEqual(spec["values"]["brightness"], 7)
            self.assertEqual(spec["values"]["initial_color"],
                             read_toml(FIXTURE)["services"]["colors"]["config"]["initial_color"])
            overlay.write_text('[services.colors]\nmemory = { arena = "RAM" }\nsource = "elsewhere"\n')
            with self.assertRaises(PackageError):
                load_project(FIXTURE, overlay, BOARD)

    def test_runtime_delivery_and_instance_isolation(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary))
            for name, value in [("config.first", 2), ("config.second", 7)]:
                store.install(self.package(value, name))
            store.configure({"config.first": "1.0.0", "config.second": "1.0.0"})
            runtime = NativeRuntime(store, BUILD / "micros-control", store.plan())
            try:
                for instance in runtime.instances.values():
                    # Running services cannot receive configuration mutations.
                    self.assertNotEqual(
                        runtime.command(f"CONFIGURE {instance} 00", allow_error=True)[
                            "result"
                        ],
                        0,
                    )
            finally:
                runtime.close()
            logs = (store.root / "runtime.log").read_text()
            self.assertIn("brightness=2\n", logs)
            self.assertIn("brightness=7\n", logs)

    def test_malformed_configuration_rejects_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary))
            store.install(self.package(7, corrupt=True))
            store.configure({"config.colors": "1.0.0"})
            with self.assertRaises(PackageError):
                NativeRuntime(store, BUILD / "micros-control", store.plan())

    def test_package_identity_includes_config_but_executable_does_not(self):
        a, b = map(read_package, (self.package(2), self.package(7)))
        self.assertEqual(a["image"], b["image"])
        self.assertNotEqual(a["sha256"], b["sha256"])
        description = copy.deepcopy(a["manifest"])
        for payload in ("ff" * 257, "not hex", "A0", "0"):
            description["config"] = payload
            with self.assertRaises(PackageError):
                build_package(description, a["image"], {})


if __name__ == "__main__":
    unittest.main()
