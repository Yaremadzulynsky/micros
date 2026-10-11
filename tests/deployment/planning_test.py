"""Deployment plans explain verified state without touching a physical board."""

import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from micros_tooling.deployment.deploy import NO_BANK
from micros_tooling.deployment.planning import deployment_plan, format_plan


def receipt():
    channel = dict(key=1, name="button.state", access="publish", depth=8, max_payload=64)
    details = {
        "button": dict(version="1.0.0", settings=dict(debounce_ms=40), configuration_hex="28",
                       memory=dict(stack_bytes=4096, arena_bytes=128),
                       capabilities=dict(handles=3, timers=1, gpio=[0]), channels=[channel],
                       board_bindings=dict(gpio=[dict(line=0, pin=38, direction="input")])),
        "colors": dict(version="1.0.0", settings=dict(brightness=8), configuration_hex="08",
                       memory=dict(stack_bytes=4096, arena_bytes=256),
                       capabilities=dict(handles=2, timers=0, gpio=[1]),
                       channels=[dict(channel, access="subscribe")]),
    }
    return dict(id="old-release", firmware_sha256="base", banks={"0": "old-graph"},
                packages=["package-a", "package-b"], details=details,
                resources=dict(image_bytes=1024),
                services=[dict(name=n, version="1.0.0") for n in details])


def inspected(unchanged=False):
    return dict(before=dict(identity=dict(device_id="aabbccddeeff", base_sha256="base"),
                            activation=dict(good=0, good_sha256="old-graph", pending=0),
                            services=[dict(state="Running", result=0)] * 2),
                unchanged=unchanged, candidate=1, plan={})


class PlanningTests(unittest.TestCase):
    def test_selective_preview_and_shared_layout_fallback(self):
        old = receipt()
        for i, detail in enumerate(old["details"].values()):
            detail["slot"] = i
            detail["image_sha256"] = str(i) * 64
            detail["board_bindings"] = copy.deepcopy(old["details"]["button"]["board_bindings"])
        new = copy.deepcopy(old)
        new["details"]["colors"]["settings"]["brightness"] = 9
        new["details"]["colors"]["configuration_hex"] = "09"
        state = inspected()
        state["before"]["selective_deploy"] = 1
        report = deployment_plan(state, old, new)
        self.assertEqual(report["execution"]["restart_scope"], "selective")
        self.assertEqual(report["execution"]["affected_services"], ["colors"])
        self.assertFalse(report["execution"]["stops_current_graph"])
        self.assertIn("Stage while current services run", format_plan(report))
        forced = deployment_plan(state, old, new, force=True)
        self.assertTrue(forced["execution"]["stops_current_graph"])
        for detail in new["details"].values(): detail["channels"][0]["depth"] = 4
        report = deployment_plan(state, old, new)
        self.assertEqual(report["execution"]["restart_scope"], "whole_application")

    def test_setting_pin_channel_and_service_changes(self):
        old = receipt()
        new = copy.deepcopy(old)
        new["id"] = "new-release"
        new["details"]["button"]["settings"]["debounce_ms"] = 60
        new["details"]["button"]["configuration_hex"] = "3c"
        new["details"]["button"]["board_bindings"]["gpio"][0]["pin"] = 14
        new["details"]["button"]["channels"][0]["depth"] = 16
        del new["details"]["colors"]
        new["services"] = new["services"][:1]
        report = deployment_plan(inspected(), old, new)
        changes = {tuple(c["path"]): c for c in report["changes"]}
        self.assertEqual(changes[("services", "button", "settings", "debounce_ms")]["after"], 60)
        self.assertEqual(changes[("services", "button", "board_bindings", "gpio", "0", "pin")]["before"], 38)
        self.assertEqual(changes[("services", "button", "channels", "1:publish", "depth")]["after"], 16)
        self.assertEqual(changes[("services", "colors")]["action"], "remove")
        self.assertNotIn(("services", "button", "configuration_hex"), changes)
        self.assertEqual(report["resources"]["requested_stack_bytes"]["delta"], -4096)
        self.assertEqual(report["resources"]["channel_payload_bytes"], dict(before=512, after=1024, delta=512))
        self.assertTrue(report["execution"]["stops_current_graph"])
        self.assertEqual(report["execution"]["affected_services"], ["button", "colors"])
        self.assertIn("all current services pause", format_plan(report))

    def test_unknown_baseline_does_not_claim_additions_or_zero_resources(self):
        report = deployment_plan(inspected(), None, receipt())
        self.assertEqual(report["baseline"]["state"], "unknown")
        self.assertTrue(all(c["action"] == "select" for c in report["changes"]))
        self.assertIsNone(report["resources"]["requested_stack_bytes"]["before"])
        self.assertIsNone(report["resources"]["requested_stack_bytes"]["delta"])
        self.assertIn("Previous configuration unknown", format_plan(report))

    def test_empty_board_is_a_known_empty_baseline(self):
        inspection = inspected()
        inspection["before"]["activation"]["good"] = NO_BANK
        inspection["before"]["services"] = []
        report = deployment_plan(inspection, None, receipt())
        self.assertEqual(report["baseline"]["state"], "empty")
        self.assertTrue(all(c["action"] == "add" for c in report["changes"]))
        self.assertEqual(report["resources"]["requested_stack_bytes"]["delta"], 8192)

    def test_wrong_graph_or_base_receipt_is_not_used_as_baseline(self):
        for field, value in (("banks", {"0": "other-graph"}), ("firmware_sha256", "other-base")):
            with self.subTest(field=field):
                old = receipt()
                old[field] = value
                self.assertEqual(deployment_plan(inspected(), old, receipt())["baseline"]["state"], "unknown")

    def test_noop_restart_and_force_are_distinct_actions(self):
        inspection = inspected(unchanged=True)
        old = receipt()
        report = deployment_plan(inspection, old, old)
        self.assertEqual(report["execution"]["action"], "none")
        self.assertEqual(report["changes"], [])
        inspection["before"]["services"] = []
        report = deployment_plan(inspection, old, old)
        self.assertEqual(report["execution"]["action"], "restart")
        self.assertFalse(report["execution"]["flash_writes"])
        report = deployment_plan(inspection, old, old, force=True)
        self.assertEqual(report["execution"]["action"], "deploy")
        self.assertTrue(report["execution"]["flash_writes"])

    def test_partial_old_metadata_does_not_invent_field_additions(self):
        old = receipt()
        del old["details"]["colors"]
        report = deployment_plan(inspected(), old, receipt())
        self.assertEqual(report["changes"], [])
        self.assertIsNone(report["resources"]["requested_stack_bytes"]["before"])
        self.assertTrue(report["warnings"])

    def test_reordered_channels_and_bindings_do_not_change_plan(self):
        old = receipt()
        old["details"]["button"]["channels"].append(dict(key=2, access="publish", depth=1, max_payload=32))
        old["details"]["button"]["board_bindings"]["gpio"].append(dict(line=1, pin=0))
        new = copy.deepcopy(old)
        new["details"]["button"]["channels"].reverse()
        new["details"]["button"]["board_bindings"]["gpio"].reverse()
        self.assertEqual(deployment_plan(inspected(True), old, new)["changes"], [])

    def test_named_settings_unavailable_retains_binary_configuration_diff(self):
        old = receipt()
        new = copy.deepcopy(old)
        del old["details"]["colors"]["settings"]
        new["details"]["colors"]["configuration_hex"] = "10"
        report = deployment_plan(inspected(), old, new)
        self.assertEqual(report["changes"][0]["path"], ["services", "colors", "configuration_hex"])
        self.assertTrue(report["warnings"])

    def test_admission_resources_override_descriptive_metadata(self):
        inspection = inspected()
        inspection["plan"]["resources"] = dict(image_bytes=2048, channel_bytes=1024)
        report = deployment_plan(inspection, receipt(), receipt())
        self.assertEqual(report["resources"]["image_bytes"]["delta"], 1024)
        self.assertEqual(report["resources"]["channel_payload_bytes"]["after"], 1024)

    def test_plan_cannot_dispatch_a_platform_writer(self):
        from micros_tooling import dispatch as cli
        from micros_tooling.storage.packages import PackageError
        with patch.object(sys, "argv", ["micros", "plan", "--platform", "esp8266"]), \
             patch("micros_tooling.platforms.handler_for") as handler:
            with self.assertRaisesRegex(PackageError, "currently support ESP32"):
                cli.main()
            handler.return_value.assert_not_called()

    def test_plan_parser_defaults_to_read_only(self):
        from micros_tooling import dispatch as cli
        args = cli.parser().parse_args(["plan", "--release", "build/review", "--force"])
        self.assertEqual(args.command, "deploy")
        self.assertTrue(args.dry_run)
        self.assertTrue(args.planning)
        self.assertTrue(args.force)


if __name__ == "__main__":
    unittest.main()
