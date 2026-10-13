import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from micros_tooling.platforms.embedded.telemetry import expand


class TelemetryTest(unittest.TestCase):
    def test_shared_controller_layout_preserves_fields_and_physical_slot(self):
        report=dict(platform='esp8266', embedded_layout=1, layout_version=2, active=1,
                    image_slots=[2], base_ota=dict(slot=0,version=1),
                    board=dict(gpio=[dict(pin=6)]),
                    services=[dict(name='example.hello',state='Running',stack_free_bytes=600)])
        result=expand(report)
        self.assertEqual(result['services'],report['services'])
        self.assertEqual(result['board']['gpio'],report['board']['gpio'])
        parts=sorted(result['flash']['partitions'],key=lambda part:part['offset'])
        end=0
        for part in parts:
            self.assertEqual(part['offset'],end);end+=part['size']
        self.assertEqual(end,result['flash']['total_bytes'])
        image=next(part for part in parts if part.get('image'))
        self.assertEqual(image['image']['slot'],2)
        self.assertEqual(image['name'],'example.hello')
        self.assertNotIn('image_bytes',image['image'])
        self.assertEqual(expand(result),result)
        for slots in ([0,1],[4],[True],[1,1]):
            with self.assertRaises(ValueError): expand(dict(report,image_slots=slots))

    def report(self):
        return dict(
            platform="esp8266",
            embedded_telemetry=1,
            active=0,
            base_ota=dict(slot=0, version=1),
            service_rows=[
                [
                    "blink",
                    "1.0",
                    4,
                    0,
                    100,
                    2,
                    128,
                    2048,
                    1600,
                    8,
                    2,
                    4,
                    1,
                    1,
                    1,
                    0,
                    0,
                    100,
                    20,
                    30,
                    500,
                ]
            ],
            channel_rows=[],
            gpio_rows=[[2, 1, 0]],
        )

    def test_all_flash_accounted_without_overlap(self):
        for slot in (0, 1):
            for bank in (0, 1, 0xFFFFFFFF):
                r = self.report()
                r["base_ota"]["slot"] = slot
                r["active"] = bank
                result = expand(r)
                end = 0
                for p in sorted(result["flash"]["partitions"], key=lambda p: p["offset"]):
                    self.assertEqual(p["offset"], end)
                    end += p["size"]
                self.assertEqual(end, 4 * 1024 * 1024)
                images = [p for p in result["flash"]["partitions"] if p.get("image")]
                self.assertEqual(len(images), int(bank < 2))
                if images:
                    self.assertEqual(
                        images[0]["offset"], slot * 0x100000 + 0xC0000 + bank * 0x20000 + 4096
                    )

    def test_schema_and_existing_platform(self):
        r = expand(self.report())
        self.assertEqual(r["services"][0]["state"], "Running")
        self.assertEqual(r["board"]["gpio"][0]["pin"], 2)
        self.assertEqual(expand(r), r)
        existing = dict(platform="esp32", services=[])
        self.assertIs(expand(existing), existing)

    def test_malformed_table(self):
        r = self.report()
        r["service_rows"][0].pop()
        with self.assertRaises(ValueError):
            expand(r)


if __name__ == "__main__":
    unittest.main()
