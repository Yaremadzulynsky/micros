"""A lost chunk reply may retry only in the original verified staging slot."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from micros_tooling.platforms.esp8266 import base_ota as ota
from micros_tooling.storage.packages import PackageError

class ChunkRetryTest(unittest.TestCase):
    def run_update(self, changed=False, rejected=False, advanced=False):
        class Remote:
            def __init__(self): self.commands=[]; self.reads=0
            def status(self):
                self.reads+=1
                if self.reads==1: return dict(base_sha256='aa'*32,pending=0,base_ota=dict(version=1,pending=0,slot=0,slot_bytes=720896))
                if self.reads==2: return dict(base_sha256=('cc' if changed else 'aa')*32,base_ota=dict(staging=1,written=128 if advanced else 0))
                return dict(base_sha256='bb'*32,base_ota=dict(slot=1,pending=0))
            def request(self,command,allow_error=False):
                previous=self.commands.count(command); self.commands.append(command)
                if command.startswith('BASE_WRITE 0 ') and previous==0:
                    if rejected: return dict(result=-1)
                    raise TimeoutError('reply lost')
                return dict(result=0)
        remote=Remote()
        with tempfile.TemporaryDirectory() as temp:
            firmware=Path(temp)/'base.elf';firmware.with_suffix('.bin').write_bytes(bytes(512))
            with patch.object(ota,'base_info',return_value=dict(hash=bytes.fromhex('bb'*32))),patch.object(ota.time,'sleep'):
                if changed or advanced:
                    with self.assertRaisesRegex(PackageError,'interrupted'): ota.update(remote,firmware)
                else: self.assertTrue(ota.update(remote,firmware)['confirmed'])
        return remote.commands

    def test_lost_reply_retries_only_chunk(self):
        commands=self.run_update()
        self.assertEqual(sum(c.startswith('BASE_BEGIN') for c in commands),1)
        self.assertEqual(sum(c.startswith('BASE_WRITE 0 ') for c in commands),2)
        self.assertEqual(commands.count('BASE_ACTIVATE'),1)

    def test_changed_base_prevents_retry_and_activation(self):
        commands=self.run_update(changed=True)
        self.assertEqual(sum(c.startswith('BASE_WRITE 0 ') for c in commands),1)
        self.assertNotIn('BASE_ACTIVATE',commands)

    def test_rejected_chunk_retries_after_reading_unchanged_write_position(self):
        commands=self.run_update(rejected=True)
        self.assertEqual(sum(c.startswith('BASE_WRITE 0 ') for c in commands),2)
        self.assertEqual(commands.count('BASE_ACTIVATE'),1)

    def test_unexpected_partial_position_prevents_retry_and_activation(self):
        commands=self.run_update(rejected=True,advanced=True)
        self.assertEqual(sum(c.startswith('BASE_WRITE 0 ') for c in commands),1)
        self.assertNotIn('BASE_ACTIVATE',commands)

    def test_persistent_rejection_is_bounded_and_uses_clean_cli_error_type(self):
        class Remote:
            def __init__(self): self.commands=[]
            def status(self):
                return dict(base_sha256='aa'*32,pending=0,
                            base_ota=dict(version=1,pending=0,slot=0,slot_bytes=720896,
                                          staging=1,written=0))
            def request(self,command,allow_error=False):
                self.commands.append(command)
                return dict(result=-1 if command.startswith('BASE_WRITE') else 0)
        remote=Remote()
        with tempfile.TemporaryDirectory() as temp:
            firmware=Path(temp)/'base.elf';firmware.with_suffix('.bin').write_bytes(bytes(512))
            with patch.object(ota,'base_info',return_value=dict(hash=bytes.fromhex('bb'*32))),patch.object(ota.time,'sleep'):
                with self.assertRaisesRegex(ValueError,'rejected'):
                    ota.update(remote,firmware)
        self.assertEqual(sum(c.startswith('BASE_WRITE') for c in remote.commands),3)
        self.assertNotIn('BASE_ACTIVATE',remote.commands)

if __name__ == '__main__': unittest.main()
