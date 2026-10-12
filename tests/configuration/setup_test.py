"""Physical setup compilation: typed wiring, resource checks, and existing output."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from micros_tooling.config.composition import compose, describe, toml, write
from micros_tooling.config.configuration import load_project, read_toml
from micros_tooling.fleet.coordination import compile_routes


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "message.proto").write_text('syntax = "proto3"; message Value { uint32 value = 1; }\n')
        contract = dict(name="test.value", interface="test.value", major=1, minor=0,
                        accepts_minor=[0, 0], max_payload=16, schema="message.proto")
        self.save("value.toml", {"interface": contract})
        self.save("frames.toml", {"interface": dict(contract, name="test.frames", interface="test.frames")})
        state = dict(interface="../value.toml", kind="state")
        frames = dict(interface="../frames.toml", policy="stream", depth=8)
        self.manifest("producer", publications={"target": state})
        self.manifest("receiver", subscriptions={"target": state}, publications={"frames": frames},
                      capabilities=dict(gpio=["rx", "tx"], timers=0),
                      hardware=dict(rx=dict(direction="input", fixed_pin=27), tx=dict(direction="output", fixed_pin=25)),
                      requirements=dict(profiles=["adafruit_feather_esp32_v2"], exclusive=["esp32.rmt"]))
        self.manifest("console", subscriptions={"frames": frames})
        self.doc = dict(setup=dict(format=1, name="Test setup"), management=dict(server=dict(url="https://example.com")),
                        devices=dict(
                            sender=dict(id="000000000001", board="esp8266_4mb",
                                        services=dict(producer=dict(manifest="producer/service.toml"))),
                            receiver=dict(id="000000000002", board="adafruit_feather_esp32_v2", services=dict(
                                receiver=dict(manifest="receiver/service.toml", pins=dict(rx=27, tx=25)),
                                console=dict(manifest="console/service.toml")))),
                        connections=[{"from": "sender.producer.target", "to": "receiver.receiver.target", "name": "target"},
                                     {"from": "receiver.receiver.frames", "to": "receiver.console.frames"}],
                        captures=dict(frames={"from": "receiver.receiver.frames"}))

    def save(self, name, document):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(toml(document))
        return path

    def manifest(self, name, **extra):
        definition = dict(name=f"test.{name}", version="1.0.0", build=dict(sources=["service.c"]),
                          capabilities=dict(gpio=[], timers=0), memory=dict(arena="RAM", stack_bytes=2048))
        definition.update(extra)
        path = self.save(f"{name}/service.toml", {"service": definition})
        (path.parent / "service.c").write_text("/* Fixture source; compose does not compile or execute it. */\n")

    def resolve(self):
        return compose(self.save("setup.toml", self.doc))

    def test_local_channel_network_route_capture_and_existing_recipe_loader(self):
        result = self.resolve()
        unit = result["units"]["receiver"]
        producer = unit["services"]["receiver"]["publications"]["frames"]["channel"]
        self.assertEqual(unit["services"]["console"]["subscriptions"]["frames"]["channel"], producer)
        self.assertEqual(unit["services"]["bridge"]["subscriptions"]["frames"]["channel"], producer)
        self.assertEqual(len(unit["channels"]), 2)
        self.assertEqual(len(result["coordination"]["routes"]), 1)
        output = write(result, self.root / "review")
        recipe = load_project(output / "units/000000000002.toml")
        self.assertEqual([s["slot"] for s in recipe["services"]], [0, 1, 2])
        self.assertEqual(recipe["board"]["gpio"][0]["pin"], 27)
        self.assertTrue(all(Path(s["sources"][0]).is_absolute() for s in recipe["services"]))
        roster = {identity: dict(online=True, status=dict(identity=dict(abi_revision=7, base_sha256="b" * 64),
                    activation=dict(good_sha256="a" * 64, sequence=1))) for identity in ("000000000001", "000000000002")}
        self.assertEqual(compile_routes(output / "coordination.toml", roster)["routes"][0]["kind"], "state")
        preview = describe(result)
        for text in ("rx = GPIO27", "network state:", "local:", "capture:", "generated for capture", "esp32.rmt"):
            self.assertIn(text, preview)

    def test_missing_wrong_direction_duplicate_and_mismatched_sources(self):
        changes = [
            (lambda d: d["connections"].pop(), "required input has no source"),
            (lambda d: d["connections"][0].update(to="receiver.receiver.missing"), "Unknown endpoint"),
            (lambda d: d["connections"][0].update(to="receiver.receiver.frames"), "subscriptions port"),
            (lambda d: d["connections"].append(dict(d["connections"][0])), "input already has a source"),
            (lambda d: d["connections"][0].update(to="receiver.console.frames"), "contracts differ"),
            (lambda d: d.pop("management"), "requires management.server.url"),
        ]
        original = copy.deepcopy(self.doc)
        for change, message in changes:
            with self.subTest(message=message):
                self.doc = copy.deepcopy(original)
                change(self.doc)
                with self.assertRaisesRegex(ValueError, message):
                    self.resolve()

    def test_streams_across_devices_are_not_silently_treated_as_coordination(self):
        sender = self.doc["devices"]["sender"]
        sender["services"]["console"] = self.doc["devices"]["receiver"]["services"].pop("console")
        self.doc["connections"][1]["to"] = "sender.console.frames"
        with self.assertRaisesRegex(ValueError, "ordinary cross-device streams are unsupported"):
            self.resolve()

    def test_hardware_constraints_and_unknown_fields(self):
        changes = [
            (lambda d: d["devices"]["receiver"]["services"]["receiver"]["pins"].update(rx=26), "requires GPIO27"),
            (lambda d: d["devices"]["receiver"]["services"]["receiver"]["pins"].pop("tx"), "pins must bind exactly"),
            (lambda d: d["devices"]["receiver"].update(board="esp8266_4mb"), "driver supports only"),
            (lambda d: d["devices"]["receiver"].update(board="feather_typo"), "unsupported setup board profile"),
            (lambda d: d["devices"]["receiver"].update(id="000000000001"), "Hardware ID selected twice"),
            (lambda d: d["devices"]["receiver"]["services"]["receiver"].update(pin={"rx": 27}), "allowed"),
            (lambda d: d["setup"].update(format=2), "setup.format"),
            (lambda d: d.update(management=[]), "Unknown management setting"),
            (lambda d: d["devices"]["receiver"].update(build=[]), "allowed"),
            (lambda d: d["devices"]["receiver"].update(channel_keys={"receiver.frames": True}), "expected integer"),
        ]
        original = copy.deepcopy(self.doc)
        for change, message in changes:
            with self.subTest(message=message):
                self.doc = copy.deepcopy(original)
                change(self.doc)
                with self.assertRaisesRegex(ValueError, message):
                    self.resolve()

    def test_exclusive_gpio_and_peripherals(self):
        manifest = self.root / "console/service.toml"
        original = read_toml(manifest)
        for extra, message in [
            ({"requirements": {"exclusive": ["esp32.rmt"]}}, "peripheral esp32.rmt already owned"),
            ({"capabilities": {"gpio": ["rx"], "timers": 0}, "hardware": {"rx": {"direction": "input"}}}, "GPIO27 already owned"),
        ]:
            with self.subTest(message=message):
                definition = copy.deepcopy(original)
                definition["service"].update(extra)
                self.save("console/service.toml", definition)
                selection = self.doc["devices"]["receiver"]["services"]["console"]
                if "hardware" in extra:
                    selection["pins"] = {"rx": 27}
                with self.assertRaisesRegex(ValueError, message):
                    self.resolve()

    def test_pinned_keys_and_deterministic_automatic_keys(self):
        first = self.resolve()
        reordered = dict(reversed(list(self.doc["devices"]["receiver"]["services"].items())))
        self.doc["devices"]["receiver"]["services"] = reordered
        second = self.resolve()
        self.assertEqual(first["units"]["receiver"]["channels"], second["units"]["receiver"]["channels"])
        self.doc["devices"]["receiver"]["channel_keys"] = {"receiver.frames": 7, "receiver.target": 3}
        pinned = self.resolve()["units"]["receiver"]
        self.assertEqual(pinned["channels"]["receiver_frames"]["key"], 7)
        self.doc["devices"]["receiver"]["channel_keys"]["console.frames"] = 8
        with self.assertRaisesRegex(ValueError, "already assigned through another port"):
            self.resolve()

    def test_interface_contract_and_capture_validation(self):
        original = copy.deepcopy(self.doc)
        for source in ("receiver.receiver.target", "sender.producer.target"):
            self.doc["captures"]["frames"]["from"] = source
            with self.assertRaises(ValueError):
                self.resolve()
        self.doc = original
        altered = read_toml(self.root / "value.toml")
        altered["interface"]["major"] = 2
        self.save("other.toml", altered)
        receiver = read_toml(self.root / "receiver/service.toml")
        receiver["service"]["subscriptions"]["target"]["interface"] = "../other.toml"
        self.save("receiver/service.toml", receiver)
        with self.assertRaisesRegex(ValueError, "contracts differ"):
            self.resolve()

    def test_capture_absence_and_source_files_are_unchanged(self):
        self.doc.pop("captures")
        self.save("setup.toml", self.doc)
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        result = compose(self.root / "setup.toml")
        self.assertNotIn("bridge", result["units"]["receiver"]["services"])
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_local_fanout_and_capture_slot_budget(self):
        frames = dict(interface="../frames.toml", policy="stream", depth=8)
        self.manifest("viewer", subscriptions={"frames": frames})
        receiver = self.doc["devices"]["receiver"]
        receiver["services"]["viewer"] = dict(manifest="viewer/service.toml")
        self.doc["connections"].append({"from": "receiver.receiver.frames", "to": "receiver.viewer.frames"})
        unit = self.resolve()["units"]["receiver"]
        self.assertEqual(len(unit["channels"]), 2)
        self.assertEqual(len(unit["services"]), 4)
        self.manifest("extra")
        receiver["services"]["extra"] = dict(manifest="extra/service.toml")
        with self.assertRaisesRegex(ValueError, "including the generated capture bridge"):
            self.resolve()
        self.doc.pop("captures")
        self.assertEqual(len(self.resolve()["units"]["receiver"]["services"]), 4)

    def test_network_fanout_is_rejected(self):
        self.manifest("other", subscriptions={"target": dict(interface="../value.toml", kind="state")})
        self.doc["devices"]["receiver"]["services"]["other"] = dict(manifest="other/service.toml")
        self.doc["connections"].append({"from": "sender.producer.target", "to": "receiver.other.target"})
        # Use a distinct channel display name so both target endpoints can be
        # represented on the receiver; a third device avoids aliasing them.
        other = self.doc["devices"]["receiver"]["services"].pop("other")
        self.doc["devices"]["third"] = dict(id="000000000003", board="esp8266_4mb", services={"other": other})
        self.doc["connections"][-1]["to"] = "third.other.target"
        with self.assertRaisesRegex(ValueError, "network fan-out is unsupported"):
            self.resolve()

    def test_board_resources_directions_and_reserved_pins(self):
        receiver = self.doc["devices"]["receiver"]
        receiver["gpio"] = dict(rx=dict(pin=27, direction="input"))
        receiver["services"]["receiver"]["pins"]["rx"] = "rx"
        self.assertEqual(self.resolve()["units"]["receiver"]["board"]["gpio"]["rx"]["pin"], 27)
        receiver["gpio"]["rx"]["direction"] = "output"
        with self.assertRaisesRegex(ValueError, "conflicts with board GPIO"):
            self.resolve()
        receiver["services"]["receiver"]["pins"]["rx"] = 27
        # Board capability validation rejects both serial pins and flash pins,
        # identifying the offending resource and pin before graph generation.
        for pin in (1, 3, 6):
            with self.subTest(pin=pin):
                receiver["gpio"] = dict(reserved=dict(pin=pin, direction="input"))
                with self.assertRaisesRegex(ValueError,
                        rf"board\.gpio\.reserved: GPIO{pin}: Reserved .*serial/flash"):
                    self.resolve()

    def test_memory_defaults_override_and_invalid_budget(self):
        service = self.doc["devices"]["receiver"]["services"]["receiver"]
        self.assertEqual(self.resolve()["units"]["receiver"]["services"]["receiver"]["memory"]["stack_bytes"], 2048)
        service["memory"] = dict(arena="RAM", stack_bytes=4096)
        self.assertEqual(self.resolve()["units"]["receiver"]["services"]["receiver"]["memory"]["stack_bytes"], 4096)
        service["memory"]["arena"] = "PSRAM"
        self.doc["devices"]["sender"]["services"]["producer"]["memory"] = dict(service["memory"])
        with self.assertRaisesRegex(ValueError, "no PSRAM"):
            self.resolve()

    def test_sdk_cli_works_outside_project_and_writes_review(self):
        setup = self.save("setup.toml", self.doc)
        output = self.root / "review"
        run = subprocess.run([str(ROOT / "micros"), "compose", str(setup), "--json", "--output", str(output)],
                             cwd="/", text=True, capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["setup"], str(setup.resolve()))
        self.assertTrue((output / "coordination.toml").is_file())
        with self.assertRaisesRegex(ValueError, "already exists"):
            write(compose(setup), output)


if __name__ == "__main__":
    unittest.main()
