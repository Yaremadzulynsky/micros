import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2] / "src"))
from micros_tooling.platforms.samd21.telemetry import expand

class TelemetryTest(unittest.TestCase):
    def report(self):
        return dict(platform='samd21',samd_telemetry=1,active=1,
            service_rows=[['blink','1.0',4,0,100,2,128,1024,600,8,2,4,1,1,1,0,0,100,20,30,500]],
            channel_rows=[[1,1,4,32,1,1,2,10,1,500,64]],gpio_rows=[[6,1,0]])
    def test_common_schema_and_idempotence(self):
        r=expand(self.report())
        self.assertEqual(r['services'][0]['state'],'Running')
        self.assertEqual(r['services'][0]['stack_free_bytes'],600)
        self.assertEqual(r['channels'][0]['published'],10)
        self.assertEqual(r['board']['gpio'][0]['pin'],6)
        self.assertEqual(r['flash']['services']['slots'][0]['offset'],65536+4096)
        self.assertEqual(expand(r),r)
        self.assertEqual(expand(self.report(),serial=True)['services'][0]['state'],4)
    def test_reserved_banks_and_slots_cover_flash(self):
        for active in (0,1,0xffffffff):
            report=self.report();report['active']=active
            parts=expand(report)['flash']['partitions']
            end=0
            for part in sorted(parts,key=lambda p:p['offset']):
                self.assertEqual(part['offset'],end);end+=part['size']
            self.assertEqual(end,262144)
            if active in (0,1):
                self.assertEqual(sum(p['size'] for p in parts if p.get('reservedCapacity')),65536+3*15360)
                self.assertEqual(len([p for p in parts if p.get('image')]),1)
    def test_ab_base_layout(self):
        report=self.report();report['layout_version']=2
        result=expand(report);parts=result['flash']['partitions']
        self.assertEqual(sum(p['size'] for p in parts),262144)
        self.assertEqual([p['size'] for p in parts if p['name'] in ('ota_0','ota_1')],[81920,81920])
        self.assertEqual(result['flash']['services']['slot_bytes'],9216)
        self.assertEqual(next(p['offset'] for p in parts if p.get('image')),0x36000+4096)
    def test_existing_platform_unchanged(self):
        r=dict(platform='esp32',services=[dict(state='Running')])
        self.assertIs(expand(r),r)
    def test_invalid_row_rejected(self):
        r=self.report();r['service_rows'][0].pop()
        with self.assertRaises(ValueError):expand(r)

if __name__=='__main__':unittest.main()
