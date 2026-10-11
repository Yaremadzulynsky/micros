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
