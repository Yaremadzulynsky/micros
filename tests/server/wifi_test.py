"""Wi-Fi input bounds, access control, and non-persistence of secret commands."""
import concurrent.futures
import json
from pathlib import Path
import struct
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from server.wifi import encode, settings
from server.relay import Registry, WIRE
import console_test

SECRET='wifi-only-sentinel-7821'
DEVICE='0123456789ab'
class WifiTests(unittest.TestCase):
    def test_encoding_and_validation(self):
        wire=encode({'networks':[{'ssid':'Home', 'password':SECRET}, None,
                                  {'ssid':'Office'}, {'ssid':'Phone', 'password':''}]})
        self.assertEqual(len(wire),404)
        self.assertEqual(wire[:8],b'MWF1'+bytes([4,len(SECRET),2,0]))
        self.assertEqual(wire[204:208],bytes([6,0,1,0]))
        for networks in ([], [None]*4, [{'ssid':'x'*33}]+[None]*3,
                         [{'ssid':'same'}]*4, [{'ssid':'x','password':'short'}]+[None]*3,
                         [{'ssid':'x','password':'z'*64}]+[None]*3,
                         [{'ssid':'x','password':False}]+[None]*3):
            with self.assertRaises(ValueError):encode({'networks':networks})
        self.assertEqual(len(encode({'networks':[{'ssid':'x','password':'a'*64}]+[None]*3})),404)

    def test_capability_and_metadata_only_read(self):
        remote=Mock();remote.status.return_value={'network':{}}
        with self.assertRaisesRegex(ValueError,'USB'):settings(remote)
        remote.request.assert_not_called()
        remote.status.return_value={'network':{'profiles_api':1}}
        remote.request.return_value={'networks':[{'ssid_hex':'486f6d65','secured':True,'fallback':False,'password':SECRET}]}
        self.assertEqual(settings(remote),{'networks':[{'ssid':'Home','secured':True,'fallback':False}]})

    def test_secret_never_in_sqlite_wal_or_result(self):
        with tempfile.TemporaryDirectory() as directory:
            registry=Registry(directory);registry.enroll(DEVICE,'test','a'*64)
            registry.db.execute('UPDATE devices SET last_seen=?',(time.time(),));registry.db.commit()
            body=encode({'networks':[{'ssid':'Home','password':SECRET}]+[None]*3})
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future=executor.submit(registry.command,DEVICE,12,0,0,0,'',body)
                deadline=time.monotonic()+3
                while not registry.private_wires and time.monotonic()<deadline:time.sleep(.005)
                self.assertTrue(registry.private_wires)
                def no_secret():
                    for p in Path(directory).glob('registry.sqlite*'):
                        self.assertNotIn(SECRET.encode(),p.read_bytes())
                no_secret()
                wire=registry.poll(DEVICE,'a'*16,{'identity':{'device_id':DEVICE}})
                self.assertEqual(wire[64:],body);self.assertFalse(registry.private_wires)
                command=wire[4:20].hex()
                # Even a faulty agent echoing input cannot put it in retained outcomes.
                registry.result(DEVICE,command,400,SECRET.encode())
                self.assertEqual(future.result(timeout=3),(400,b'{"error":"Wi-Fi settings were not confirmed saved"}'))
                registry.result(DEVICE,command,400,SECRET.encode())
                no_secret()
            registry.db.close()

    def test_private_timeout_and_restart_do_not_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            registry=Registry(directory);registry.enroll(DEVICE,'test','a'*64)
            registry.db.execute('UPDATE devices SET last_seen=?',(time.time(),));registry.db.commit()
            with patch('server.relay.COMMAND_SECONDS',.02):
                self.assertEqual(registry.command(DEVICE,12,0,0,0,'',SECRET.encode())[0],504)
            self.assertFalse(registry.private_wires);registry.db.close()
            registry=Registry(directory)
            self.assertEqual(registry.db.execute('SELECT state,wire FROM commands').fetchone(),('unknown',None))
            registry.db.close()

class WifiHttpTests(unittest.TestCase):
    setUp = console_test.ConsoleTests.setUp
    tearDown = console_test.ConsoleTests.tearDown
    request = console_test.ConsoleTests.request
    def test_wifi_route_requires_authentication_and_origin(self):
        path='/console/api/devices/'+DEVICE+'/wifi'
        payload={'networks':[{'ssid':'Home','password':SECRET}]+[None]*3}
        with patch('server.wifi.settings',return_value={'ok':True}) as call:
            self.assertEqual(self.request(path,payload,cookie='')[0],401)
            self.assertEqual(self.request(path,payload,origin='https://wrong.test')[0],403)
            call.assert_not_called()
            self.assertEqual(self.request(path,payload)[0],200)
            self.assertEqual(self.request(path)[0],200)
        for p in Path(self.directory.name).glob('registry.sqlite*'):
            self.assertNotIn(SECRET.encode(),p.read_bytes())

if __name__=='__main__':unittest.main()
