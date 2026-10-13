import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2] / "src"))
from server.wifi import settings
class Remote:
    def __init__(self):self.sent=[]
    def status(self):return dict(platform='samd21')
    def request(self,method,path,body):
        self.sent.append((method,path,body))
        return dict(result=0,networks=[dict(ssid_hex='486f6d65',secured=True)])
class WifiTest(unittest.TestCase):
    def test_pairing_reads_identity_from_status_not_wifi_profile_settings(self):
        import argparse, json, tempfile
        from unittest.mock import Mock, patch
        from micros_tooling.platforms.samd21 import cli
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            firmware = root / 'base.elf'; firmware.write_bytes(b'fixture')
            project = root / 'unit.toml'; project.write_text('[board]\n')
            remote = Mock(serial_number='usb-identity')
            remote.__enter__ = Mock(return_value=remote)
            remote.__exit__ = Mock(return_value=False)
            remote.status.return_value = dict(base_sha256='ab' * 32, identity=dict(device_id='ac1da4519140'))
            remote.request.side_effect = AssertionError('Wi-Fi settings are not a device identity')
            args = argparse.Namespace(command='init', name='mkr', phase='connect', firmware=firmware,
                                      project=project, json=True)
            with patch.object(cli, 'state_root', return_value=root), \
                 patch.object(cli, 'SerialRemote', return_value=remote), \
                 patch.object(cli, 'base_info', return_value=dict(hash=bytes.fromhex('ab' * 32))), \
                 patch.object(cli, 'emit'):
                cli.main(args)
            self.assertEqual(json.loads((root / 'devices/mkr.json').read_text())['device_id'], 'ac1da4519140')

    def test_metadata_only(self):
        r=Remote(); self.assertEqual(settings(r)['networks'],[dict(ssid='Home',secured=True,fallback=False)])
        self.assertTrue(r.sent[0][2].endswith(b' WIFI_GET'))
    def test_reported_platform_avoids_extra_radio_request(self):
        r=Remote()
        def unexpected():raise AssertionError('Unexpected extra status request')
        r.status=unexpected
        self.assertEqual(settings(r,reported_status={'platform':'samd21'})['networks'][0]['ssid'],'Home')
    def test_keep_secret(self):
        r=Remote();settings(r,dict(networks=[dict(ssid='Home',password=None)]))
        self.assertTrue(r.sent[0][2].endswith(b' WIFI_PROFILE 486f6d65 keep'))
    def test_two_profiles_atomic_and_kept_by_ssid(self):
        r=Remote();status=dict(platform='samd21',network=dict(profiles_capacity=2))
        settings(r,dict(networks=[dict(ssid='Home',password=None),dict(ssid='example',password='password123')]),reported_status=status)
        self.assertTrue(r.sent[0][2].endswith(b' WIFI_PROFILES 486f6d65 keep 6578616d706c65 70617373776f7264313233'))
        r=Remote();settings(r,dict(networks=[dict(ssid='Home',password=None),None]),reported_status=status)
        self.assertTrue(r.sent[0][2].endswith(b' WIFI_PROFILES 486f6d65 keep - -'))
        for networks in ([None,dict(ssid='Home')],[dict(ssid='Home')]*2,[dict(ssid='Home')]*3):
            r=Remote()
            with self.assertRaises(ValueError):settings(r,dict(networks=networks),reported_status=status)
            self.assertEqual(r.sent,[])

    def test_invalid_before_write(self):
        for networks in ([],[None],[dict(ssid='Home',password='short')],[dict(ssid='Home')]*2):
            r=Remote()
            with self.assertRaises(ValueError):settings(r,dict(networks=networks))
            self.assertEqual(r.sent,[])
if __name__=='__main__':unittest.main()
