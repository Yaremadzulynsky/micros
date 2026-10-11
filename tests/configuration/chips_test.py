"""Hardware capability validation stays distinct from runtime feature support."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from micros_tooling.config.chips import load_chip, board_capabilities, pin_listing
from micros_tooling.config.resources import board_definition, validate_bindings
from micros_tooling.storage.packages import PackageError


class ChipTests(unittest.TestCase):
    def board(self, pin=38, direction="input", **settings):
        return board_definition(dict(profile="adafruit_feather_esp32_v2", chip="esp32",
                                     gpio=dict(button=dict(pin=pin, direction=direction, **settings))))

    def test_gpio_groups_and_fixed_adc_mapping(self):
        chip = load_chip("esp32")
        self.assertEqual(set(chip["pins"]), set(range(40)) - {24, 28, 29, 30, 31})
        self.assertEqual(chip["pins"][38]["adc"], dict(unit=1, channel=2))
        for pin in range(34, 40):
            self.assertFalse(chip["pins"][pin]["output"])
            self.assertEqual(chip["pins"][pin]["pulls"], ["none"])
        self.assertEqual(chip["peripherals"]["rmt"]["shared_channels"], 8)

    def test_unsupported_pulls_and_output_fail(self):
        for pull in ("up", "down"):
            with self.subTest(pull=pull), self.assertRaisesRegex(PackageError, "GPIO38 does not support internal pull"):
                self.board(pull=pull)
        with self.assertRaisesRegex(PackageError, "input-only"):
            self.board(direction="output")
        with self.assertRaisesRegex(PackageError, "pull must be"):
            self.board(pull="float")

    def test_supported_hardware_pull_does_not_claim_runtime_support(self):
        self.assertIn("up", load_chip("esp32")["pins"][13]["pulls"])
        with self.assertRaisesRegex(PackageError, "not yet supported by the micros runtime"):
            self.board(pin=13, pull="up")

    def test_no_pull_preserves_legacy_board_fingerprint(self):
        self.assertEqual(self.board(), self.board(pull="none"))
        legacy = board_definition(dict(profile="adafruit_feather_esp32_v2",
                                       gpio=dict(button=dict(pin=38, direction="input"))))
        self.assertEqual(legacy, self.board())

    def test_board_and_runtime_restrictions(self):
        scl = self.board(pin=20)
        validate_bindings({key: scl[key] for key in ("gpio", "recovery_button")})
        with self.assertRaisesRegex(PackageError, "Reserved by the current micros"):
            self.board(pin=7)
        with self.assertRaisesRegex(PackageError, "not a verified"):
            self.board(pin=16)
        with self.assertRaisesRegex(PackageError, "does not exist"):
            self.board(pin=24)
        with self.assertRaisesRegex(PackageError, "requires chip esp32"):
            board_capabilities("adafruit_feather_esp32_v2", "esp32s3")

    def test_listing_distinguishes_board_pull_from_chip_pull(self):
        report = pin_listing(self.board())
        button = next(p for p in report["pins"] if p["pin"] == 38)
        self.assertEqual(button["external_pull"], "up")
        self.assertEqual(button["pulls"], ["none"])
        self.assertFalse(button["rmt_tx"])
        self.assertTrue(button["rmt_rx"])
        self.assertEqual(button["assigned"], "button")


if __name__ == "__main__":
    unittest.main()
