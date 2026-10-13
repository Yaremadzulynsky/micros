"""Hardware capability validation stays distinct from runtime feature support."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import copy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from micros_tooling.config.chips import load_chip, board_capabilities, pin_listing, format_pins, resolve_pin_type
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

    def test_esp8266_gpio16_has_rtc_pulls_and_tout_is_not_gpio(self):
        chip = load_chip("esp8266")
        self.assertEqual(set(chip["pins"]), set(range(17)))
        for pin in range(16):
            self.assertEqual(chip["pins"][pin],
                             dict(input=True, output=True, pulls=["none", "up"]))
        self.assertEqual(chip["pins"][16],
                         dict(input=True, output=True, pulls=["none", "down"]))
        self.assertFalse(any("adc" in pin for pin in chip["pins"].values()))
        self.assertNotIn("rmt", chip["peripherals"])

    def test_samd21_g18a_package_pins_use_cmsis_not_arduino_numbering(self):
        chip = load_chip("samd21")
        expected = (set(range(26)) | {27, 28, 30, 31, 34, 35, 40, 41, 42, 43, 54, 55})
        self.assertEqual(set(chip["pins"]), expected)
        self.assertEqual(chip["chip"]["part"], "SAMD21G18A")
        for pin in chip["pins"].values():
            self.assertTrue(pin["input"] and pin["output"])
            self.assertEqual(pin["pulls"], ["none", "up", "down"])
        adc = {pin: info["adc"] for pin, info in chip["pins"].items() if "adc" in info}
        expected_adc = {2: 0, 3: 1, 40: 2, 41: 3, 4: 4, 5: 5, 6: 6, 7: 7,
                        34: 10, 35: 11, 8: 16, 9: 17, 10: 18, 11: 19}
        self.assertEqual(adc, {pin: dict(unit=1, channel=channel)
                              for pin, channel in expected_adc.items()})
        self.assertNotIn("adc", chip["pins"][15])  # Arduino A0=15 maps to PA02.
        self.assertNotIn("rmt", chip["peripherals"])

    def test_mkr_catalog_maps_arduino_pins_and_does_not_reserve_d1_d3(self):
        caps = board_capabilities('arduino_mkr_wifi_1010', 'samd21')
        self.assertEqual(caps['pins'][15]['chip_pin'], 2)
        self.assertEqual(caps['pins'][16]['chip_pin'], 34)
        self.assertEqual(caps['pins'][16]['adc'], dict(unit=1, channel=10))
        for pin in (1, 3, 13, 14, 15, 21):
            board_definition(dict(profile='arduino_mkr_wifi_1010',
                                  gpio={'test': dict(pin=pin, direction='output')}))
        for pin in (22, 25, 26, 35, 36):
            with self.subTest(pin=pin), self.assertRaises(PackageError):
                board_definition(dict(profile='arduino_mkr_wifi_1010',
                                      gpio={'test': dict(pin=pin, direction='output')}))

    def test_embedded_profiles_preserve_fingerprints(self):
        cases = [('esp8266_4mb', 2, '0177a9fe700003f0b3e43804d1f3e88b09bfa06df37a74d8e694cea9e0f28545'),
                 ('arduino_mkr_wifi_1010', 6, '34cd6cf7e46beced20601c919c1d7c106355727b3f356831ce6aacce826a376c')]
        for profile, pin, fingerprint in cases:
            value = board_definition(dict(profile=profile, gpio={'led': dict(pin=pin, direction='output')}))
            self.assertEqual(value['sha256'], fingerprint)

    def test_embedded_runtime_limits_come_from_catalog(self):
        from micros_tooling.config import chips
        original = chips.read_toml
        def changed(path):
            data = copy.deepcopy(original(path))
            if path.name == 'esp8266_4mb.toml':
                data['runtime']['max_gpio_resources'] = 1
                data['runtime']['reserved'].append(4)
            return data
        with patch.object(chips, 'read_toml', side_effect=changed):
            with self.assertRaises(PackageError):
                board_definition(dict(profile='esp8266_4mb', gpio={'test': dict(pin=4, direction='input')}))
            with self.assertRaises(PackageError):
                board_definition(dict(profile='esp8266_4mb', gpio={
                    'a': dict(pin=2, direction='output'), 'b': dict(pin=5, direction='output')}))

    def test_embedded_listing_has_no_esp32_peripheral_claims(self):
        for profile, pin in [('esp8266_4mb', 16), ('arduino_mkr_wifi_1010', 15)]:
            report = pin_listing(dict(profile=profile))
            self.assertTrue(all(not row['rmt_tx'] and not row['rmt_rx'] for row in report['pins']))
            for options in ({}, {'all_pins': True}, {'pin_number': pin}):
                output = format_pins(report, **options)
                self.assertNotIn('share 8 hardware channels', output)
                self.assertNotIn('transmit and receive', output)
            with self.assertRaisesRegex(PackageError, 'analog GPIO is not supported'):
                resolve_pin_type(dict(profile=profile), pin, 'analog', 'test')
        output = format_pins(pin_listing(dict(profile='esp8266_4mb')), pin_number=16)
        self.assertIn('Internal resistors: pull-down', output)
        self.assertNotIn('pull-up', output.split('Internal resistors:')[1].splitlines()[0])

    def test_invalid_board_chip_mapping_is_rejected(self):
        from micros_tooling.config import chips
        original = chips.read_toml
        for target in (999, 22, None):
            def changed(path):
                data = copy.deepcopy(original(path))
                if path.name == 'arduino_mkr_wifi_1010.toml':
                    data['gpio']['15']['chip_pin'] = target
                return data
            with self.subTest(target=target), patch.object(chips, 'read_toml', side_effect=changed):
                with self.assertRaisesRegex(PackageError, 'chip pin'):
                    board_capabilities('arduino_mkr_wifi_1010')

    def test_wroom_module_exposure_and_runtime_restrictions(self):
        profile = 'esp32_wroom_32e'
        caps = board_capabilities(profile, 'esp32')
        self.assertEqual(set(caps['board']['exposed']),
                         {0, 1, 2, 3, 4, 5, 12, 13, 14, 15, 16, 17, 18, 19,
                          21, 22, 23, 25, 26, 27, 32, 33, 34, 35, 36, 39})
        for pin in (16, 17, 23, 27):
            value = board_definition(dict(profile=profile, gpio={'test': dict(pin=pin, direction='output')}))
            self.assertEqual(value['gpio'][0]['pin'], pin)
        for pin in (1, 3, 6, 11, 20, 37, 38):
            with self.subTest(pin=pin), self.assertRaises(PackageError):
                board_definition(dict(profile=profile, gpio={'test': dict(pin=pin, direction='input')}))
        for pin in (34, 35, 36, 39):
            with self.subTest(pin=pin), self.assertRaisesRegex(PackageError, 'input-only'):
                board_definition(dict(profile=profile, gpio={'test': dict(pin=pin, direction='output')}))
        with self.assertRaisesRegex(PackageError, 'does not support internal pull'):
            board_definition(dict(profile=profile, gpio={'test': dict(pin=34, direction='input', pull='up')}))
        report = pin_listing(dict(profile=profile))
        self.assertIn('IO16', format_pins(report, pin_number=16))
        self.assertNotIn('SW38', format_pins(report, all_pins=True))

    def test_wroom_flash_default_and_override_preserve_feather_default(self):
        self.assertEqual(board_definition(dict(profile='esp32_wroom_32e'))['flash_mb'], 4)
        self.assertNotIn('flash_mb', board_definition(dict(profile='esp32_wroom_32e', flash_mb=8)))
        self.assertNotIn('flash_mb', board_definition(dict(profile='adafruit_feather_esp32_v2')))
        with self.assertRaisesRegex(PackageError, '4 or 8'):
            board_definition(dict(profile='esp32_wroom_32e', flash_mb=16))

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
