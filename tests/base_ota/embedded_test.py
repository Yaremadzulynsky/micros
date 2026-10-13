"""An unreconciled chunk failure must never activate or replay a write."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from micros_tooling.platforms.esp8266.base_ota import update


class Remote:
    def __init__(self, fail=False):
        self.relay = object()  # Chunked mode must not invoke the downloader API.
        self.commands = []
        self.fail = fail

    def status(self):
        return dict(pending=False, base_sha256='ab' * 32,
                    base_ota=dict(version=1, pending=False, slot=int(bool(self.commands)), slot_bytes=720896))

    def request(self, command, *, allow_error=False):
        self.commands.append(command)
        if self.fail and command.startswith('BASE_WRITE'):
            raise TimeoutError('outcome unknown')
        return {'result': 0}


class EmbeddedBaseTest(unittest.TestCase):
    def test_chunk_transfer_and_uncertain_write(self):
        with tempfile.TemporaryDirectory() as directory:
            firmware = Path(directory) / 'base.elf'
            data = bytes(range(256)) + b'abcd'
            firmware.with_suffix('.bin').write_bytes(data)
            with patch('micros_tooling.platforms.esp8266.base_ota.base_info', return_value=dict(hash=bytes.fromhex('ab' * 32))), \
                 patch('micros_tooling.platforms.esp8266.base_ota.time.sleep'):
                remote = Remote()
                self.assertTrue(update(remote, firmware, chunked=True)['confirmed'])
                self.assertEqual(remote.commands[0], f'BASE_BEGIN 1 260 {hashlib.sha256(data).hexdigest()}')
                self.assertEqual(remote.commands[1], 'BASE_WRITE 0 ' + data[:256].hex())
                self.assertEqual(remote.commands[2], 'BASE_WRITE 256 ' + (b'abcd' + b'\xff' * 60).hex())
                self.assertEqual(remote.commands[3], 'BASE_ACTIVATE')
                remote = Remote(fail=True)
                with self.assertRaisesRegex(ValueError, 'inspect status'):
                    update(remote, firmware, chunked=True)
                self.assertEqual(len(remote.commands), 2)


if __name__ == '__main__':
    unittest.main()
