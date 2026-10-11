"""Damaged USB reads recover; ambiguous provisioning writes are never replayed."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from micros_tooling.platforms.embedded.transport import EmbeddedRemote, SerialResponseError
from micros_tooling.storage.packages import PackageError


class Serial:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.writes = []
        self.clears = 0
    def write(self, data):
        self.writes.append(data)
    def read_until(self, *args):
        return next(self.replies)
    def reset_input_buffer(self):
        self.clears += 1


class SerialTransportTest(unittest.TestCase):
    def remote(self, replies):
        r = EmbeddedRemote()
        r.session = '0123456789abcdef0123456789abcdef'
        r.platform = 'esp8266'
        r.target = 6
        r.serial = Serial(replies)
        return r

    def valid(self, **overrides):
        return (json.dumps(dict(result=0, platform='esp8266', target=6, activation=dict(candidate=0xffffffff,pending=0,good=0xffffffff), identity=dict(base_sha256='0'*64), **overrides)) + '\n').encode()

    def test_status_recovers_from_malformed_json_without_reopening(self):
        r = self.remote([b'{"result" 0}\n', self.valid()])
        with patch('micros_tooling.platforms.embedded.transport.time.sleep'):
            self.assertEqual(r.status()['target'], 6)
        self.assertEqual(r.serial.writes, [b'RPC 0 0 0 0 - -\n'] * 2)
        self.assertEqual(r.serial.clears, 1)

    def test_wifi_log_inserted_inside_status_is_discarded(self):
        r = self.remote([b'{"result":0,"platform":"\x1b[0;32mI (8944) tcpip_adapter: sta ip ready\x1b[0m\r\n',
                         b'esp8266","target":6}\n', self.valid()])
        with patch('micros_tooling.platforms.embedded.transport.time.sleep'):
            self.assertEqual(r.status()['target'], 6)
        self.assertEqual(len(r.serial.writes), 2)

    def test_invalid_utf8_status_is_retried(self):
        r = self.remote([b'{"result":0,"text":"\xff"}\n', self.valid()])
        with patch('micros_tooling.platforms.embedded.transport.time.sleep'):
            self.assertEqual(r.status()['platform'], 'esp8266')

    def test_retry_limit_is_actionable_and_bounded(self):
        r = self.remote([b'{"broken"}\n'] * 3)
        with patch('micros_tooling.platforms.embedded.transport.time.sleep'), self.assertRaisesRegex(PackageError, 'three attempts'):
            r.status()
        self.assertEqual(len(r.serial.writes), 3)
        self.assertEqual(r.serial.clears, 2)

    def test_provisioning_reply_failure_is_unknown_and_never_replayed(self):
        secret = 'private-password'
        r = self.remote([b'{"echo":"private-password",broken}\n'])
        r._session_open = True  # A malformed mutation reply must never trigger a retry.
        with self.assertRaises(SerialResponseError) as error:
            r.request('WIFI_SET ' + b'network'.hex() + ' ' + secret.encode().hex())
        self.assertEqual(error.exception.outcome, 'unknown')
        self.assertNotIn(secret, str(error.exception))
        self.assertEqual(len(r.serial.writes), 1)
        self.assertEqual(r.serial.clears, 0)

    def test_wrong_platform_is_not_retried(self):
        r = self.remote([b'{"result":0,"platform":"other","target":6}\n'])
        with self.assertRaisesRegex(PackageError, 'Unexpected device platform'):
            r.status()
        self.assertEqual(len(r.serial.writes), 1)

    def test_split_reply_and_boot_noise_need_no_retry(self):
        r = self.remote([b'boot diagnostic\n', self.valid()[:12], self.valid()[12:]])
        self.assertEqual(r.status()['target'], 6)
        self.assertEqual(len(r.serial.writes), 1)


if __name__ == '__main__':
    unittest.main()
