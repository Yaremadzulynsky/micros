from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from micros_tooling.communication.channels import Channels, ChannelMissed

class Remote:
    def __init__(self):
        self.reply = "IPC EMPTY 2"
        self.calls = []
    def request(self, method, path, body):
        self.calls.append((method, path, body))
        if isinstance(self.reply, Exception):
            raise self.reply
        return {"reply": self.reply}

class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.remote = Remote()
        self.client = Channels(self.remote, ROOT / "examples/network-bridge/micros.toml")
    def test_forward(self):
        self.assertIsNone(self.client.read("outbound"))
        self.remote.reply = "IPC DATA 2 082a"
        self.assertEqual(self.client.read("outbound"), b"\x08\x2a")
        self.remote.reply = "IPC QUEUED 1"
        self.client.write("inbound", b"\x08\x2a")
        self.assertEqual(self.remote.calls[-1], ("POST", "/v1/platform-command", b"IPC WRITE 0 1 082a"))
    def test_subscriber_first_runtime_order(self):
        bridge = {"name": "board.bridge", "slot": 0, "_interface": {"name": "bridge", "ports": [
            {"name": "input", "access": "publish", "key": 1, "max_payload": 64}]}}
        subscriber = {"name": "board.z", "slot": 1, "_interface": {"name": "z", "ports": []}}
        with patch("micros_tooling.communication.channels.load_project", return_value={"services": [bridge, subscriber]}):
            channels = Channels(self.remote, "unused")
        self.remote.reply = "IPC QUEUED 1"
        channels.write("input", b"x")
        self.assertEqual(self.remote.calls[-1][2], b"IPC WRITE 1 1 78")

    def test_no_retry(self):
        for error in (TimeoutError("lost acknowledgement"),):
            self.remote.reply = error
            with self.assertRaises(TimeoutError): self.client.write("inbound", b"\x08\x01")
        self.assertEqual(len(self.remote.calls), 1)
    def test_bounds_and_direction(self):
        for port, payload in (("outbound", b"x"), ("inbound", b""), ("inbound", b"x" * 65)):
            with self.assertRaises(ValueError): self.client.write(port, payload)
        self.client.ports["inbound"]["max_payload"] = 256
        with self.assertRaises(ValueError): self.client.write("inbound", b"x" * 128)
        with self.assertRaises(ValueError): self.client.read("inbound")
        self.assertEqual(self.remote.calls, [])
    def test_loss_and_bad_reply(self):
        self.remote.reply = "IPC ERROR -10"
        with self.assertRaises(ChannelMissed): self.client.read("outbound")
        self.remote.reply = "IPC DATA 1 0801"
        with self.assertRaises(RuntimeError): self.client.read("outbound")
        self.remote.reply = "IPC ERROR -3"
        with self.assertRaises(RuntimeError): self.client.read("outbound")

if __name__ == "__main__": unittest.main()
