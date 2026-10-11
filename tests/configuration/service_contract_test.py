"""Reusable service contracts, stable APIs and isolated instance bindings."""
import copy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from micros_tooling.config.composition import toml
from micros_tooling.config.configuration import load_project, generate_service_headers
from micros_tooling.config.protobuf import RUNTIME, RUNTIME_SOURCES
from micros_tooling.storage.packages import PackageError


class ServiceContractTests(unittest.TestCase):
    def test_resolved_json_cannot_bypass_declaration_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'recipe.json'
            path.write_text('{"format":1,"services":[]}')
            with self.assertRaisesRegex(ValueError, 'must be TOML'):
                load_project(path)
            self.assertEqual([p.name for p in Path(directory).iterdir()], ['recipe.json'])

    def setUp(self):
        output = ROOT / "build/tests/service-contract"
        output.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=output)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.root / "units").mkdir()
        self.path = self.root / "units/aabbccddeeff.toml"
        schema = ROOT / "src/sdk/protos/button/v1/button_state.proto"
        self.channel = dict(interface="micros.button.state", major=1, minor=1,
                            accepts_minor=[1, 1], policy="stream", depth=8,
                            max_payload=64, schema=str(schema))
        self.contract = dict(name="example.sensor", version="1.0.0",
            build=dict(api="sensor", sources=["service.c"], defines=[]),
            capabilities=dict(gpio=["input"], timers=1),
            config_schema=dict(period=dict(type="uint32", default=20, min=1, max=100)),
            hardware=dict(input=dict(direction="input")),
            subscriptions=dict(events=self.channel))
        selection = {}
        selection.update(source="../source", contract="service.toml", memory=dict(arena="RAM"),
                         config=dict(period=30), gpio_bindings=dict(input="front"),
                         subscriptions=dict(events=dict(channel="presses")))
        self.document = dict(unit=dict(device_id="aabbccddeeff"),
            board=dict(profile="esp32", flash_mb=4,
                       gpio=dict(front=dict(pin=13, direction="input"), rear=dict(pin=14, direction="input"))),
            services=dict(first=selection),
            channels=dict(presses=dict(self.channel, key=1, name="button.front")))
        (self.source / "service.c").write_text('''#include "sensor_ipc.h"
#include "sensor_resources.h"
#include "sensor_config.h"
micros_result_t use_service(const micros_service_args_t *args) {
    micros_handle_t gpio, channel;
    sensor_config_t config;
    micros_result_t result = sensor_config_decode(0, 0, &config);
    if (!result) result = sensor_input_open(args, &gpio);
    return result ? result : sensor_events_open(args, &channel);
}
''')
        self.write()

    def write(self):
        (self.source / "service.toml").write_text(toml(dict(service=self.contract)))
        self.path.write_text(toml(self.document))

    def test_unit_cannot_repeat_implementation_facts_even_when_equal(self):
        compact = load_project(self.path)
        for field in ("version", "build", "capabilities", "config_schema"):
            with self.subTest(field=field):
                self.document["services"]["first"][field] = copy.deepcopy(self.contract[field])
                self.write()
                with self.assertRaisesRegex(PackageError, field + " belongs"):
                    load_project(self.path)
                del self.document["services"]["first"][field]
        self.write()
        self.assertEqual(compact, load_project(self.path))

    def test_inline_gpio_preserves_board_identity_and_resource_grants(self):
        original = load_project(self.path)
        binding = self.document["board"]["gpio"].pop("front")
        self.document["services"]["first"]["gpio_bindings"]["input"] = dict(binding, name="front")
        self.write()
        self.assertEqual(original, load_project(self.path))
        # Disabling the service does not change physical wiring or base identity.
        self.document["services"]["first"]["enabled"] = False
        self.write()
        self.assertEqual(original["board"], load_project(self.path)["board"])

    def test_inline_gpio_rejects_conflicting_declarations_and_wrong_direction(self):
        binding = self.document["board"]["gpio"]["front"]
        self.document["services"]["first"]["gpio_bindings"]["input"] = dict(binding, name="front")
        self.write()
        with self.assertRaisesRegex(PackageError, "already declared"):
            load_project(self.path)
        del self.document["board"]["gpio"]["front"]
        self.document["services"]["first"]["gpio_bindings"]["input"]["direction"] = "output"
        self.write()
        with self.assertRaisesRegex(PackageError, "direction mismatch"):
            load_project(self.path)

    def test_inline_gpio_rejects_duplicate_physical_pins(self):
        del self.document["board"]["gpio"]["front"]
        self.document["services"]["first"]["gpio_bindings"]["input"] = dict(pin=14, direction="input")
        self.write()
        with self.assertRaisesRegex(PackageError, "already assigned"):
            load_project(self.path)

    def test_rebinding_and_two_instances_keep_api_and_dispatch(self):
        second = copy.deepcopy(self.document["services"]["first"])
        second["name"] = "example.rear-sensor"
        second["gpio_bindings"]["input"] = "rear"
        second["subscriptions"]["events"]["channel"] = "rear_presses"
        self.document["services"]["rear"] = second
        self.document["channels"]["rear_presses"] = dict(self.channel, key=2, name="button.rear")
        self.write()
        generate_service_headers(self.path)
        recipe = load_project(self.path)
        directories = []
        for index, service in enumerate(recipe["services"]):
            spec = service["_interface"]
            self.assertEqual(spec["name"], "sensor")
            self.assertEqual(service["sources"][0], str(self.source / "service.c"))
            self.assertEqual(service["capabilities"]["handles"], 3)
            adapter = Path(spec["directory"]) / "generated"
            generated = Path(service["_contract"]["directory"]) / "generated"
            directories.append(adapter)
            harness = generated / "check.c"
            harness.write_text('''#include <assert.h>
#include <micros/service.h>
#include <micros/ipc.h>
extern micros_result_t use_service(const micros_service_args_t *);
static micros_result_t gpio_open(micros_context_t *c, uint32_t line, micros_handle_t *h) {
    (void)c; assert(line == EXPECT_LINE); *h = 1; return MICROS_OK;
}
static micros_result_t ipc_open(micros_context_t *c, uint32_t key, uint32_t access, micros_handle_t *h) {
    (void)c; assert(key == EXPECT_KEY); assert(access == MICROS_IPC_SUBSCRIBE); *h = 2; return MICROS_OK;
}
int main(void) {
    const struct micros_ipc_api ipc = { .ipc_open = ipc_open };
    const micros_api_t api = { .gpio_open = gpio_open, ._ipc = &ipc };
    const micros_service_args_t args = { .api = &api };
    assert(use_service(&args) == MICROS_OK);
}
''')
            binary = generated / "check"
            command = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                       f"-DEXPECT_KEY={index + 1}", f"-DEXPECT_LINE={index}"]
            for include in (generated, RUNTIME, ROOT / "src/sdk/abi/include", ROOT / "src/sdk/abi/internal"):
                command += ["-I", str(include)]
            command += [str(self.source / "service.c"), str(harness), str(generated / "sensor_ipc.c"), str(adapter / "sensor_bindings.c")]
            command += [str(p) for p in generated.glob("*.pb.c")]
            command += [str(p) for p in RUNTIME_SOURCES]
            result = subprocess.run(command + ["-o", str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            subprocess.run([str(binary)], check=True)
        self.assertNotEqual(*directories)
        self.assertFalse((self.source / "generated").exists())

    def test_units_sharing_source_do_not_overwrite_each_other(self):
        generate_service_headers(self.path)
        first = Path(load_project(self.path)["services"][0]["_interface"]["directory"]) / "generated/sensor_bindings.c"
        before = first.read_bytes()
        shared = Path(load_project(self.path)["services"][0]["_contract"]["directory"]) / "generated"
        interface_before = {p.name:p.read_bytes() for p in shared.iterdir()}
        self.document["unit"]["device_id"] = "112233445566"
        self.path = self.path.with_name("112233445566.toml")
        self.document["channels"]["presses"]["key"] = 7
        self.write()
        generate_service_headers(self.path)
        second = Path(load_project(self.path)["services"][0]["_interface"]["directory"]) / "generated/sensor_bindings.c"
        self.assertNotEqual(first, second)
        self.assertNotEqual(before, second.read_bytes())
        self.assertEqual(first.read_bytes(), before)
        self.assertEqual(interface_before, {p.name:p.read_bytes() for p in shared.iterdir()})

    def test_rejects_changed_requirements(self):
        original = copy.deepcopy(self.document)
        for field, replacement in (("version", "2.0.0"), ("build", dict(api="other", sources=["service.c"])),
                                   ("capabilities", dict(gpio=["input"], timers=0)), ("config_schema", {})):
            with self.subTest(field=field):
                self.document = copy.deepcopy(original)
                self.document["services"]["first"][field] = replacement
                self.write()
                with self.assertRaisesRegex(PackageError, field + " belongs"):
                    load_project(self.path)

    def test_rejects_missing_extra_or_wrong_direction_ports(self):
        original = copy.deepcopy(self.document)
        for change in ("missing", "extra", "direction"):
            with self.subTest(change=change):
                self.document = copy.deepcopy(original)
                service = self.document["services"]["first"]
                if change == "missing": service["subscriptions"] = {}
                if change == "extra": service["subscriptions"]["surprise"] = dict(channel="presses")
                if change == "direction": service["publications"] = service.pop("subscriptions")
                self.write()
                with self.assertRaisesRegex(PackageError, "bind exactly"):
                    load_project(self.path)

    def test_rejects_channel_contract_drift(self):
        original = copy.deepcopy(self.document)
        changes = dict(interface="wrong.type", major=2, minor=0, accepts_minor=[0, 1],
                       policy="latest", depth=1, max_payload=32)
        for field, value in changes.items():
            with self.subTest(field=field):
                self.document = copy.deepcopy(original)
                self.document["channels"]["presses"][field] = value
                self.write()
                with self.assertRaisesRegex(PackageError, "channel .* mismatch|invalid accepts_minor|invalid policy/depth"):
                    load_project(self.path)

    def test_rejects_schema_contents_even_with_matching_identity(self):
        altered = self.root / "altered.proto"
        altered.write_text(Path(self.channel["schema"]).read_text().replace("uint32 sequence", "uint64 sequence"))
        self.document["channels"]["presses"]["schema"] = str(altered)
        self.write()
        with self.assertRaisesRegex(PackageError, "schema mismatch"):
            generate_service_headers(self.path)
        self.assertFalse((self.root / "build").exists())

    def test_rejects_gpio_direction_and_missing_bindings(self):
        self.document["board"]["gpio"]["front"]["direction"] = "output"
        self.write()
        with self.assertRaisesRegex(PackageError, "direction mismatch"):
            load_project(self.path)
        self.document["services"]["first"]["gpio_bindings"] = {}
        self.write()
        with self.assertRaisesRegex(PackageError, "gpio_bindings"):
            load_project(self.path)

    def test_compose_validates_setting_values_without_generating(self):
        self.document["services"]["first"]["config"]["period"] = 0
        self.write()
        with self.assertRaisesRegex(PackageError, "expected integer"):
            load_project(self.path)

    def test_contract_is_required_when_declared(self):
        (self.source / "service.toml").unlink()
        with self.assertRaisesRegex(ValueError, "service.toml"):
            load_project(self.path)


if __name__ == "__main__":
    unittest.main()
