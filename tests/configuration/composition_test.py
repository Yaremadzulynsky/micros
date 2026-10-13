"""Offline composition preserves current recipes and rejects broken topology."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from micros_tooling.config.composition import compose, write, toml
from micros_tooling.config.configuration import load_project, read_toml, select_unit
from micros_tooling.fleet.coordination import compile_routes
from micros_tooling.storage.packages import PackageError


def normalized(value):
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalized(item) for item in value]
    if isinstance(value, str) and value.startswith(str(ROOT)):
        return str(Path(value).resolve())
    return value


class CompositionTests(unittest.TestCase):
    def changed(self, mutate):
        path = ROOT / "tests/fixtures/composition/deployments/ir.toml"
        doc = copy.deepcopy(read_toml(path))
        mutate(doc)
        original = read_toml
        with patch("micros_tooling.config.composition.read_toml",
                   side_effect=lambda p: doc if Path(p) == path else original(p)):
            return compose(path)

    def test_fixture_units_keep_service_slots_contracts_settings_and_wiring(self):
        checked = set()
        for name in ("ir", "ir-wroom", "dht"):
            result = compose(ROOT / f"tests/fixtures/composition/deployments/{name}.toml")
            with tempfile.TemporaryDirectory() as tmp:
                output = write(result, Path(tmp) / "review")
                for unit in result["units"].values():
                    identity = unit["unit"]["device_id"]
                    generated = select_unit(output / "units", identity)
                    self.assertEqual(normalized(load_project(generated)),
                                     normalized(load_project(ROOT / f"tests/fixtures/composition/units/{identity}.toml")))
                    checked.add(identity)
                # Compiled files enter the existing live-admission compiler.
                roster = {identity: dict(online=True, status=dict(
                    identity=dict(abi_revision=7, base_sha256="b" * 64),
                    activation=dict(good_sha256="a" * 64, sequence=1))) for identity in checked}
                routes = compile_routes(output / "coordination.toml", roster)
                self.assertEqual(len(routes["routes"]), len(result["coordination"]["routes"]))
                self.assertTrue(all(r["drop_first"] == 0 for r in routes["routes"]))
        self.assertEqual(len(checked), 4)

    def test_bad_connections(self):
        changes = [
            lambda d: d["connections"][0].update(to="missing.ir.target"),
            lambda d: d["connections"][0].update(to="feather.ir.frames"),
            lambda d: d["connections"][0].update(to="feather.ir.operations"),
            lambda d: d["connections"].append(dict(d["connections"][0], name="duplicate_endpoint")),
            lambda d: d["connections"][0].update(drop_first=True),
            lambda d: d["connections"][0].update(drop_first=101),
            lambda d: d["connections"][0].update(typo="ignored?"),
            lambda d: d["connections"][1].update(name=d["connections"][0]["name"]),
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(PackageError):
                self.changed(change)

    def test_device_identity_missing_file_and_capture_direction(self):
        changes = [
            lambda d: d["devices"]["feather"].update(id=d["devices"]["controller"]["id"]),
            lambda d: d["devices"]["feather"].update(id="../../escape"),
            lambda d: d["devices"]["feather"].update(board="missing.toml"),
            lambda d: d["streams"]["frames"].update(**{"from": "feather.ir.target"}),
            lambda d: d["streams"]["frames"].update(**{"from": "controller.controller.target"}),
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(PackageError):
                self.changed(change)

    def test_loader_enforces_hardware_grants_and_configuration_bounds(self):
        with self.assertRaisesRegex(PackageError, "has no GPIO"):
            self.changed(lambda d: d["devices"]["feather"].update(board="../boards/esp32-no-controls.toml"))
        path = ROOT / "tests/fixtures/composition/applications/ir-receiver.toml"
        app = copy.deepcopy(read_toml(path))
        app["services"]["monitor"]["config"]["sample_interval_ms"] = 0
        original = read_toml
        with patch("micros_tooling.config.composition.read_toml",
                   side_effect=lambda p: app if Path(p) == path else original(p)):
            with self.assertRaisesRegex(PackageError, "expected integer"):
                compose(ROOT / "tests/fixtures/composition/deployments/ir.toml")

    def test_no_capture_means_no_bridge_slot(self):
        result = self.changed(lambda d: d.pop("streams"))
        self.assertNotIn("bridge", result["units"]["feather"]["services"])

    def test_relative_paths_are_independent_of_working_and_output_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = subprocess.run([str(ROOT / "micros"), "compose", str(ROOT / "tests/fixtures/composition/deployments/ir.toml"),
                                  "--output", str(Path(tmp) / "review"), "--json"],
                                 cwd=tmp, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            result = json.loads(run.stdout)
            self.assertEqual(len(result["units"]), 2)
            self.assertTrue((Path(tmp) / "review/coordination.toml").is_file())

    def test_existing_reviews_are_never_overwritten(self):
        result = compose(ROOT / "tests/fixtures/composition/deployments/ir.toml")
        with tempfile.TemporaryDirectory() as tmp:
            output = write(result, Path(tmp) / "review")
            before = (output / "coordination.toml").read_bytes()
            with self.assertRaisesRegex(PackageError, "already exists"):
                write(result, output)
            self.assertEqual((output / "coordination.toml").read_bytes(), before)

    def test_toml_round_trip(self):
        import tomli
        data = {"title": "quotes \" and newline\n", "list": [1, True, "hello"],
                "empty": {}, "routes": [{"from": "a.b.c"}, {"from": "x.y.z"}]}
        self.assertEqual(tomli.loads(toml(data)), data)


if __name__ == "__main__":
    unittest.main()
